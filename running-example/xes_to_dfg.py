"""Convert a XES event log into a directly-follows graph (DFG) in JSON.

Requires Python 3.9 or newer. No additional packages are needed.

Run in a terminal:
    python xes_to_dfg.py running-example.xes dfg.json

The JSON is a list of objects containing:
    start_activity: source activity of the relation (not the case start)
    end_activity: target activity of the relation (not the case end)
    frequency: number of times this consecutive pair occurs in all cases
    performance: mean elapsed time between the pair's timestamps, in seconds

Performance includes any waiting between events; it is not a measure of
activity execution time alone. Only consecutive events within the same trace
(case) are connected. No artificial start or end nodes are added.

Events are processed in their stored XES order. This program expects events
in each trace to be in chronological order and reports an error otherwise.
For equal timestamps, the original event order is preserved.
"""

import argparse                      # Read filenames from the command line.
import json                          # Write Python data as JSON.
import xml.etree.ElementTree as ET    # XES files contain XML.
from datetime import datetime, timezone
from pathlib import Path

from pytz import tzinfo


def local_tag(element):
    """Remove an optional XML namespace, so both XES variants work."""
    # For example, '{http://www.xes-standard.org/}event' becomes 'event'.
    return element.tag.rsplit("}", 1)[-1]


def read_event(event, trace_number, event_number):
    """Extract an event's activity name and timestamp, with useful errors."""
    # A dictionary lets us find attributes by their keys, regardless of order.
    attributes = {child.get("key"): child.get("value") for child in event}
    activity = attributes.get("concept:name")
    timestamp_text = attributes.get("time:timestamp")
    location = f"Trace {trace_number}, event {event_number}"

    # Do not skip invalid events: skipping could invent a directly-follows edge.
    if not activity or not timestamp_text:
        raise ValueError(f"{location}: concept:name and time:timestamp are required.")

    try:
        # 'Z' means UTC; replacing it also works with older Python versions.
        timestamp = datetime.fromisoformat(timestamp_text.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"{location}: invalid timestamp {timestamp_text!r}.") from error

    # If no offset is provided, assign the chosen default timezone.
    # replace() keeps the recorded clock time unchanged.
    if timestamp.utcoffset() is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    # Convert all timestamps to UTC before calculating elapsed time.
    return activity, timestamp.astimezone(timezone.utc)


def xes_to_dfg(input_path):
    """Read the log and return one JSON-ready dictionary per DFG relation."""
    root = ET.parse(input_path).getroot()
    if local_tag(root) != "log":
        raise ValueError("The XML root must be a XES 'log' element.")

    # Each key is an activity pair, for example ('check ticket', 'decide').
    # Each value stores a count and the sum of observed elapsed seconds.
    edge_statistics = {}
    traces = [child for child in root if local_tag(child) == "trace"]

    for trace_number, trace in enumerate(traces, start=1):
        events = [child for child in trace if local_tag(child) == "event"]
        # Reset for every case to avoid connecting events from different cases.
        previous = None

        for event_number, event in enumerate(events, start=1):
            current = read_event(event, trace_number, event_number)

            if previous is not None:
                start_activity, start_time = previous
                end_activity, end_time = current
                elapsed_seconds = (end_time - start_time).total_seconds()

                if elapsed_seconds < 0:
                    raise ValueError(
                        f"Trace {trace_number}, event {event_number}: "
                        "events are not in chronological order."
                    )

                edge = (start_activity, end_activity)
                if edge not in edge_statistics:
                    edge_statistics[edge] = {"frequency": 0, "total_seconds": 0.0}

                edge_statistics[edge]["frequency"] += 1
                edge_statistics[edge]["total_seconds"] += elapsed_seconds

            previous = current

    # Turn the accumulated statistics into the requested list of objects.
    dfg = []
    for (start_activity, end_activity), statistics in edge_statistics.items():
        frequency = statistics["frequency"]
        mean_seconds = statistics["total_seconds"] / frequency
        dfg.append({
            "start_activity": start_activity,
            "end_activity": end_activity,
            "frequency": frequency,
            "performance": round(mean_seconds, 3),
        })

    # Show the most frequent relations first, like the supplied example.
    # Ties retain their order of first appearance in the log.
    dfg.sort(key=lambda edge: edge["frequency"], reverse=True)
    return dfg


def main():
    """Read command-line arguments, convert the log, and save the JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to the input .xes file")
    parser.add_argument("output", type=Path, help="Path to the output .json file")
    args = parser.parse_args()

    # Protect the source log from accidental overwriting.
    if args.input.resolve() == args.output.resolve():
        parser.error("Input and output must be different files.")

    try:
        dfg = xes_to_dfg(args.input)
        with args.output.open("w", encoding="utf-8") as output_file:
            # indent=2 makes the JSON readable. Activity names keep Unicode.
            json.dump(dfg, output_file, indent=2, ensure_ascii=False, allow_nan=False)
            output_file.write("\n")
    except (OSError, ET.ParseError, ValueError) as error:
        parser.exit(status=1, message=f"Error: {error}\n")

    print(f"Saved {len(dfg)} DFG relations to {args.output}")
    # Also print the simple textual representation requested in the example.
    with open(args.output, "r", encoding="utf-8") as file:
        print(file.read())


# Run main() only when this file is executed, not when it is imported.
if __name__ == "__main__":
    main()
