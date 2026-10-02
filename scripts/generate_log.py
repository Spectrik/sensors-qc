"""Generate a large deterministic log using constant working memory."""
import argparse
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--sensors", type=int, default=10)
parser.add_argument("--readings", type=int, default=100000)
args = parser.parse_args()
if args.sensors < 1 or args.readings < 1:
    parser.error("sensors and readings must be positive")
out = sys.stdout
out.write("reference 70 45\n")
for sensor in range(args.sensors):
    out.write(f"thermometer temp-{sensor}\n")
    for reading in range(args.readings):
        out.write(f"2007-04-05T22:00 {69 + reading % 3}\n")
