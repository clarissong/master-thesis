import re
import textwrap
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


def save_redesign_excel(text, output_folder="."):
    sheet_names = {
        "A": "Data Interpretation",
        "B": "Transition Metrics",
        "C": "Bottleneck Candidates",
        "D": "Redesign Recommendations",
        "E": "Validation Plan",
    }

    # Find each main section and preserve its title and content.
    sections = {
        match.group(1): (match.group(2).strip(), match.group(3))
        for match in re.finditer(
            r"^##\s+([A-Z])\.\s+([^\n]+)\n(.*?)(?=^##\s+[A-Z]\.|\Z)",
            text,
            flags=re.MULTILINE | re.DOTALL,
        )
    }

    missing = set(sheet_names) - sections.keys()
    if missing:
        raise ValueError(f"Missing sections: {', '.join(sorted(missing))}")

    def clean(value):
        # Remove Markdown emphasis and inline-code delimiters.
        return value.replace("**", "").replace("`", "").strip()

    def split_row(line):
        return [clean(cell) for cell in line.strip().strip("|").split("|")]

    def is_separator(line):
        cells = split_row(line)
        return bool(cells) and all(
            re.fullmatch(r":?-+:?", cell) for cell in cells
        )

    def convert_value(value):
        # Convert only complete numeric cells; keep IDs and prose as text.
        if re.fullmatch(
            r"-?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?", value
        ):
            number = value.replace(",", "")
            return float(number) if "." in number else int(number)
        return value

    def estimated_lines(value, width):
        return sum(
            max(1, len(textwrap.wrap(line, width=max(10, int(width)))))
            for line in str(value).split("\n")
        )

    workbook = Workbook()
    workbook.remove(workbook.active)

    for section, sheet_name in sheet_names.items():
        title, content = sections[section]
        worksheet = workbook.create_sheet(sheet_name)
        lines = content.strip().splitlines()

        table_lines = [
            line for line in lines if line.strip().startswith("|")
        ]
        column_count = max(
            (len(split_row(line)) for line in table_lines),
            default=1,
        )

        # Table sheets use multiple columns; prose-only sheets use one wide column.
        if column_count == 1:
            widths = [120]
        elif section == "B":
            widths = [12, 46, 14, 24, 18, 28]
        else:
            widths = [45] * column_count

        for column, width in enumerate(widths, start=1):
            worksheet.column_dimensions[get_column_letter(column)].width = width

        row_number = 1

        def write_text(value, bold=False, title_row=False):
            nonlocal row_number

            value = clean(value)
            worksheet.merge_cells(
                start_row=row_number,
                start_column=1,
                end_row=row_number,
                end_column=column_count,
            )
            cell = worksheet.cell(row_number, 1, value)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.font = Font(
                bold=bold,
                size=14 if title_row else 11,
                color="24476A" if bold else "000000",
            )

            # Estimate merged-cell text wrapping.
            usable_width = sum(widths) * 0.85
            height = estimated_lines(value, usable_width) * 16 + 10
            worksheet.row_dimensions[row_number].height = min(
                409, max(28, height)
            )
            row_number += 1

        write_text(f"{section}. {title}", bold=True, title_row=True)
        row_number += 1

        index = 0
        while index < len(lines):
            line = lines[index].strip()

            if not line:
                row_number += 1
                index += 1
                continue

            if line.startswith("|"):
                # Process one contiguous Markdown table.
                table_start = row_number
                header = True

                while index < len(lines) and lines[index].strip().startswith("|"):
                    table_line = lines[index].strip()
                    index += 1

                    if is_separator(table_line):
                        continue

                    values = split_row(table_line)
                    if len(values) != column_count:
                        raise ValueError(
                            f"Inconsistent table row in section {section}: "
                            f"{table_line}"
                        )

                    for column, value in enumerate(values, start=1):
                        value = value if header else convert_value(value)
                        cell = worksheet.cell(row_number, column, value)
                        cell.alignment = Alignment(
                            wrap_text=True, vertical="top"
                        )

                        if header:
                            cell.font = Font(bold=True, color="FFFFFF")
                            cell.fill = PatternFill(
                                "solid", fgColor="24476A"
                            )
                        elif isinstance(value, (int, float)):
                            cell.number_format = (
                                "#,##0.00"
                                if isinstance(value, float)
                                else "#,##0"
                            )

                    line_count = max(
                        estimated_lines(value, width - 3)
                        for value, width in zip(values, widths)
                    )
                    worksheet.row_dimensions[row_number].height = min(
                        409, max(30, line_count * 16 + 10)
                    )

                    row_number += 1
                    header = False

                worksheet.freeze_panes = f"A{table_start + 1}"
                continue

            # Keep prose, list items, and subsection headings.
            is_heading = line.startswith("#")
            if is_heading:
                line = re.sub(r"^#+\s*", "", line)

            write_text(line, bold=is_heading)
            index += 1

        worksheet.sheet_view.showGridLines = False

    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    output_path = (
        output_folder / f"{date.today():%Y-%m-%d}_Redesign_Suggestion.xlsx"
    )
    workbook.save(output_path)

    return output_path