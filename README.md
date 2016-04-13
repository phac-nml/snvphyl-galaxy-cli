# SNVPhyl CLI

This project contains a command-line interface for the [SNVPhyl][] Galaxy pipeline.  This enables execution, via a command-line script, an instance of the SNVPhyl pipeline installed in either a previously established [Galaxy][] instance, or a local [Docker][] container based on the [Galaxy Docker][] project.

# Installation

The SNVPhyl CLI requires [Python][] along with some dependency modules to be installed.  To install these please run:

```bash
git clone https://github.com/phac-nml/snvphyl-galaxy-cli.git
pip install -r snvphyl-galaxy-cli/requirements.txt
```

In addition, to execute a local Docker instance of the pipeline, Docker must be installed and setup to enable sudo-less execution of `docker`.  This can be accomplished with:

```bash
# Download and install Docker
curl -sSL https://get.docker.com/ | sh

# Add current user `whoami` to group docker for sudo-less execution of docker.
# You will likely have to logout/login again to refresh groups.
sudo usermod -a -G docker `whoami`
```

# Usage

## Docker

Assuming you have Docker installed, the simplest use case is to run using docker.  This can be accomplished with:

```bash
python bin/snvphyl.py --deploy-docker --fastq-dir example-data/fastqs --reference-file example-data/reference.fasta --min-coverage 5 --output-dir output1
```

This will download the current version of SNVPhyl from Docker, start it running, load the passed data files, execute the pipeline, and download the results on completion.  On first execution, there may be a delay while the Docker image is downloaded.  On completion you should see a message like:

```
Finished
========
Took 1.55 minutes
Galaxy history f2db41e1fa331b3e on http://localhost:48888
Output in output1

Undeploying and cleaning up Docker Container
=============================================
Running 'docker rm -f -v c28e98ca56423f1087714673e0d4a0175e36b250107c530a2996e92cbee3fc65'
```
Following execution the Docker container will be stopped and deleted.  If you wish to keep the Docker container around please pass `--no-undeploy-docker`.  SNVPhyl will remain running within Docker, and can be accessed by logging into <http://localhost:48888> by default with username **admin@galaxy.org** and password **admin**.

The output files will be available in the directory `output1/` on completion.  Please see the [SNVPhyl Output][] documentation for details on these files.  Additionally, provenance information from Galaxy, as well as a file listing all parameter settings `run-settings.txt` is provided.

## Galaxy

To execute SNVPhyl within an existing Galaxy installation, please run:

```bash
python bin/snvphyl.py --galaxy-url http://galaxy --galaxy-api-key 1234abcd --fastq-dir example-data/fastqs --reference-file example-data/reference.fasta --output-dir output2
```

This assumes that the address <http://galaxy> contains a running instance of Galaxy with SNVPhyl pre-installed, the API key corresponds to a valid user in Galaxy, and that the appropriate version of the SNVPhyl workflows are imported into the Galaxy user.  Please see the [SNVPhyl Galaxy][] installation documentation for more details on which workflows to use, or alternatively, pass the Galaxy workflow id with `--workflow-id`.

This will upload all required input data into Galaxy and execute SNVPhyl.  To avoid re-uploading the fastq files to Galaxy, you can run:

```bash
python bin/snvphyl.py --galaxy-url http://galaxy --galaxy-api-key 1234abcd --fastq-history-name fastq-history --reference-file example-data/reference.fasta --output-dir output3
```

This assumes that the fastq files have been previously uploaded to Galaxy in a history named **fastq-history** and a dataset collection has been prepared as described in the [SNVPhyl Documentation](https://snvphyl.readthedocs.org/en/latest/user/usage/#preparing-sequence-reads)

# Legal

Copyright 2012-2016 Government of Canada

Licensed under the Apache License, Version 2.0 (the "License"); you may not use
this work except in compliance with the License. You may obtain a copy of the
License at:

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed
under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.

[SNVPhyl]: http://snvphyl.readthedocs.org/
[Python]: https://www.python.org/
[Galaxy]: https://galaxyproject.org/
[Docker]: https://www.docker.com/
[Galaxy Docker]: https://github.com/bgruening/docker-galaxy-stable/
[SNVPhyl Output]: http://snvphyl.readthedocs.org/en/latest/user/output/
