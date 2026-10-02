# Sensor quality control

A Python command-line tool. It reads sensor logs, checks thermometer and humidity measurements against reference values, and returns the results as JSON.

You can run it locally, in Docker, or as a Kubernetes Job. It requires Python 3.11+ and has no runtime dependencies.

## Quick start

Run these commands from the project directory:

```bash
# Process the sample and print the results
python -m sensor_qc --input examples/sample.log

# Save the results to a file
python -m sensor_qc --input examples/sample.log --output results.json
```

Compare the result with `examples/expected.json`.

You can also pipe a log into the tool:

```bash
cat examples/sample.log | python -m sensor_qc
```

By default, the tool reads from stdin and writes to stdout. Results go to stdout; diagnostic logs go to stderr.

When saving to a file, its directory must already exist. The tool replaces an existing result only after the entire input passes validation. If the input is invalid, the previous result stays untouched.

### Optional installation

To use the shorter `sensor-qc` command, install the project in a virtual environment:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install .
sensor-qc --input examples/sample.log
```

Installation uses setuptools. Running `python -m sensor_qc` directly does not require it.

## How sensors are classified

| Sensor | Condition | Result |
| --- | --- | --- |
| Thermometer | Mean is within 0.5 of the reference and standard deviation is below 3 | `ultra precise` |
| Thermometer | Mean is within 0.5 of the reference and standard deviation is below 5 | `very precise` |
| Thermometer | Any other case | `precise` |
| Humidity | Every reading is within one percentage point of the reference, including the boundary | `keep` |
| Humidity | Any reading falls outside that range | `discard` |

For thermometers, standard deviation is calculated across the full set of readings (division by `n`). A single reading has a standard deviation of zero. A thermometer whose mean is too far from the reference is classified as `precise`, as specified by the assignment.

CO detectors are not implemented because the assignment does not define their evaluation rules.

## Input format

The first nonblank line contains the reference temperature and humidity. Each sensor header is followed by its readings:

```text
reference 70.0 45.0
thermometer temp-1
2007-04-05T22:00 70.0
2007-04-05T22:01 70.2
humidity hum-1
2007-04-05T22:00 45.0
```

The parser checks the whole file before publishing results:

- Use one reference line per file. Reference humidity must be between 0 and 100.
- Each sensor needs a unique name and at least one reading. Keep all readings for a sensor together in one block.
- Files must use UTF-8. Blank lines and Windows line endings are accepted.
- Timestamps must be valid ISO-style dates and times. Minutes, seconds, fractional seconds and timezone offsets are supported. Readings are not sorted or deduplicated.
- Invalid records, unknown sensor types and invalid numbers stop processing with an error that includes the line number.

The parser also limits lines to 4096 characters and numbers to 16 significant digits, an absolute decimal exponent of 16, and an absolute value of `1e12`. These are implementation limits; scientific notation is accepted within them. Negative or physically unusual readings are still evaluated.

Humidity comparisons use decimal arithmetic. Thermometer statistics use floating-point arithmetic, so results extremely close to a classification boundary may be affected by rounding.

## Run with Docker

Build the image and process the sample:

```bash
docker build -t sensor-qc:1.0.0 .

docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  --tmpfs /tmp:rw,noexec,nosuid,size=64m \
  -v "$PWD/examples:/input:ro" \
  sensor-qc:1.0.0 --input /input/sample.log
```

Or pass input through stdin:

```bash
cat examples/sample.log | docker run --rm -i sensor-qc:1.0.0
```

The container runs as UID/GID `10001`. To save results on the host, mount a writable directory at `/output` and add `--output /output/results.json`. On Linux, make sure that UID/GID can write to the directory.

The read-only container uses `/tmp` for temporary results. For large outputs, use a mounted output directory with enough free space.

If you build on ARM and run on an AMD64 cluster, build an image for the cluster's architecture or publish a multi-platform image.

## Run in Kubernetes

The Helm chart runs the tool as a Job: it processes one file and exits. Job status tells you whether processing succeeded, so HTTP health checks are unnecessary.

You need a Kubernetes cluster, Helm 3, kubectl, and a container image the cluster can access. The chart does not create the cluster, registry or persistent storage.

### Local demo with kind

With Docker, kind, kubectl and Helm installed:

```bash
kind create cluster --name sensor-qc
docker build -t sensor-qc:1.0.0 .
kind load docker-image sensor-qc:1.0.0 --name sensor-qc

helm install demo helm/sensor-qc
kubectl wait --for=condition=complete job/demo-sensor-qc --timeout=120s
kubectl logs job/demo-sensor-qc
```

The demo stores the assignment sample in a ConfigMap and prints results to the pod logs. Logs include both results and diagnostics. ConfigMaps are suitable for this small demo; use file storage for larger inputs.

If the Job does not complete, check its pods, events and logs:

```bash
kubectl get pods
kubectl describe job demo-sensor-qc
kubectl logs job/demo-sensor-qc
```

### Process files using PVCs

Create an input PVC named `sensor-input` containing `batch-001.log`, and an output PVC named `sensor-output`. Then run:

```bash
helm install batch-001 helm/sensor-qc -f examples/values-pvc.yaml \
  --set image.repository=YOUR_REGISTRY/sensor-qc \
  --set image.tag=1.0.0

kubectl wait --for=condition=complete job/batch-001-sensor-qc --timeout=3600s
kubectl logs job/batch-001-sensor-qc
```

Input is mounted read-only at `/input`. Results are saved to `/output/batch-001.json`.

For your cluster, check that:

- The image is available in your registry. Private registries may require an existing Secret configured through `imagePullSecrets`.
- Storage permissions allow UID/GID `10001` to read input and write output.
- Each batch has a unique output filename, so Jobs do not overwrite each other's results.
- The Job completed successfully before you use its output. An existing file alone does not prove that the latest run succeeded.

Use a new Helm release name for each batch, or uninstall the previous release before running it again. Kubernetes restricts changes to existing Job pod templates, so `helm upgrade` may fail when changing Job settings.

By default, completed Jobs and pods are removed after one hour. The Helm release and demo ConfigMap remain until you uninstall them. Save any logs you need before cleanup.

### Validate the chart

```bash
bash scripts/check_helm.sh
helm template demo helm/sensor-qc > rendered.yaml

# Optional: validate against an existing cluster
kubectl apply --dry-run=server -f rendered.yaml
```

## Tests and CI

Run the tests:

```bash
python -m unittest discover -s tests -v
```

Tests cover the sample, classification boundaries, invalid input, streaming, CLI output and preserving existing results when processing fails.

GitHub Actions runs the tests, validates the Helm chart, builds and smoke-tests the container, and checks the ZIP package. Deployment and image publishing are not configured.

To try a larger input:

```bash
python scripts/generate_log.py --sensors 10 --readings 100000 > /tmp/large.log
python -m sensor_qc --input /tmp/large.log --output /tmp/large-results.json
```

To create a ZIP of the project:

```bash
python scripts/package.py
```

The packaging script excludes caches and build files, then verifies the archive against the source files.

## How it works

| File | Responsibility |
| --- | --- |
| `parser.py` | Read and validate the log |
| `evaluators.py` | Calculate statistics and classify sensors |
| `cli.py` | Handle input, output, logs and exit codes |

Readings are processed one at a time instead of loading the whole file into memory. Thermometers maintain a running mean and variance using Welford's algorithm. Humidity sensors track whether any reading is outside the allowed range.

Processing time grows with the number of readings. Memory grows with the number of unique sensor names, which are kept to detect duplicates. Temporary disk space grows with the size of the JSON result. Large stdout results spill to disk after 1 MiB.

Successful runs log sensor and reading counts, line count and duration to stderr. Failed runs log the error.

| Exit code | Meaning |
| --- | --- |
| `0` | Success |
| `2` | Invalid input or command-line arguments |
| `1` | Input/output failure |

## Larger workloads and next steps

The tool handles one file per process. For multiple independent files, run separate Jobs with unique batch names and output paths. Choose storage that supports the access your Jobs need; a single ReadWriteOnce PVC is not general shared storage for multiple nodes.

A single large file is processed sequentially. Splitting it would need to preserve reference values and complete sensor blocks, or correctly merge partial statistics for each sensor.

Possible future additions include object-storage input/output, run it as a service with queue for assigning batches to workers, and production monitoring (use an endpoint which would expose statistics in prometheus metrics format). These are not implemented. Terraform infrastructure is also outside the current implementation; it would depend on the chosen cloud and storage setup.

Since we have timestamps available in the readings file, we could also plot the values in nice graphs in grafana for example.

File output uses an atomic replacement on the destination filesystem. It does not guarantee power-loss durability, and a forcibly stopped process may leave a temporary file behind.
