# SNVPhyl CLI

This project contains a command-line interface for the [SNVPhyl][] Galaxy pipeline.  This enables execution, via a command-line script, an instance of the SNVPhyl pipeline installed in either a previously established [Galaxy][] instance, or a local [Docker][] container based on the [Galaxy Docker][] project.

*As an alternative, there exists a **Nextflow** version of SNVPhyl developed by **Jill Hagey** available at <https://github.com/DHQP/SNVPhyl_Nextflow>.* 

# Installation

The SNVPhyl CLI requires [Python][] along with some dependency modules to be installed.  To install these please run:

```bash
# Remove `-b master` to use latest development version of code
git clone -b master https://github.com/phac-nml/snvphyl-galaxy-cli.git
pip install -r snvphyl-galaxy-cli/requirements.txt
```

**Note: You may have to install additional Linux build tools and development libraries (e.g. `libyaml`) for some Python modules to successfully install.**

In addition, to execute a local Docker instance of the pipeline, Docker must be installed and setup to enable sudo-less execution of `docker`.  This can be accomplished with:

```bash
# Download and install Docker
curl -sSL https://get.docker.com/ | sh

# Start Docker service if not already started
sudo service docker start

# (Optional) Add current user to group docker for sudo-less execution of docker.
# You will likely have to logout/login again to refresh groups.
# If this is not run, the `docker` command will require `sudo` access, meaning you need to
# run SNVPhyl with `snvphyl.py --with-docker-sudo`.
sudo usermod -a -G docker `whoami`
```

Please see the [Docker Install][] guide for more details.

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
Following execution the Docker container will be stopped and deleted.  If you wish to keep the Docker container around please pass `--keep-docker`.  SNVPhyl will remain running within Docker, and can be accessed by logging into <http://localhost:48888> with username **admin@galaxy.org** and password **admin**.

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

### Galaxy and --fastq-files-as-links

The command-line option `--fastq-files-as-links` can be used to link to files when importing into Galaxy instead of making a copy.  This can reduce both running time and the space required.  However, this requires certain conditions to be satisifed on the Galaxy server.  Notably:

1. The option `allow_library_path_paste` should be set to **True** within the Galaxy config file `config/galaxy.ini`.
2. The fastq files should be in a directory accessible by both the `snvphyl.py` script and the Galaxy server using the same path.  E.g., `/input/data/fastq` should point to the same set of files both on the local machine and on the Galaxy server.

If you are using a Docker instance of Galaxy that has been launched independently of the `snvphyl.py` script, then you will have to mount the fastq input directory within the Docker container as a data volume.  This can be accomplished with the `-v` option in Docker.  For example:

```bash
docker run -d -p 48888:80 -v /input/data/fastq:/input/data/fastq phacnml/snvphyl-galaxy-1.0.1
```

You will have to mount within Docker under the same path in order to satisfy condition (2) above.  Please see the [Docker volume documentation][] for more details on data volumes.

# Detailed Usage

```
usage: snvphyl.py [-h] [--galaxy-url GALAXY_URL]
                  [--galaxy-api-key GALAXY_API_KEY] [--deploy-docker]
                  [--keep-docker] [--docker-port DOCKER_PORT]
                  [--docker-cpus DOCKER_CPUS] [--with-docker-sudo]
                  [--snvphyl-version SNVPHYL_VERSION]
                  [--workflow-id WORKFLOW_ID]
                  [--reference-file REFERENCE_FILE] [--output-dir OUTPUT_DIR]
                  [--fastq-dir FASTQ_DIR] [--fastq-files-as-links]
                  [--fastq-history-name FASTQ_HISTORY_NAME]
                  [--invalid-positions-file INVALID_POSITIONS_FILE]
                  [--run-name RUN_NAME]
                  [--relative-snv-abundance RELATIVE_SNV_ABUNDANCE]
                  [--min-coverage MIN_COVERAGE]
                  [--min-mean-mapping MIN_MEAN_MAPPING]
                  [--repeat-minimum-length REPEAT_MINIMUM_LENGTH]
                  [--repeat-minimum-pid REPEAT_MINIMUM_PID]
                  [--filter-density-window FILTER_DENSITY_WINDOW]
                  [--filter-density-threshold FILTER_DENSITY_THRESHOLD]
                  [--version]

Run the SNVPhyl workflow using the given Galaxy credentials and download results.

optional arguments:
  -h, --help            show this help message and exit

Galaxy API (runs SNVPhyl in external Galaxy instance):
  --galaxy-url GALAXY_URL
                        URL to the Galaxy instance to execute SNVPhyl
  --galaxy-api-key GALAXY_API_KEY
                        API key for the Galaxy instance for executing SNVPhyl

Docker (runs SNVPhyl in local Docker container):
  --deploy-docker       Deply an instance of Galaxy using Docker.
  --keep-docker         Keep docker image running after pipeline finishes.
  --docker-port DOCKER_PORT
                        Port for deployment of Docker instance [48888].
  --docker-cpus DOCKER_CPUS
                        Limit on number of CPUs docker should use. The value -1 means
                        use all CPUs available on the machine [-1]
  --docker-other-options DOCKER_OTHER_OPTIONS
                        Other docker options can be passed here. These will be directly passed
			to the `docker` command.
  --with-docker-sudo    Run `docker with `sudo` [False].

SNVPhyl Versions:
  --snvphyl-version SNVPHYL_VERSION
                        version of SNVPhyl to execute [1.0.1].
  --workflow-id WORKFLOW_ID
                        Galaxy workflow id.  If not specified attempts to guess

Input:
  --reference-file REFERENCE_FILE
                        Reference file (in .fasta format) to map reads to
  --fastq-dir FASTQ_DIR
                        Directory of fastq files (ending in .fastq, .fq, .fastq.gz, .fq.gz).
                        For paired-end data must be separated into files ending in _1/_2
                        or _R1/_R2 or _R1_001/_R2_001.
  --fastq-files-as-links
                        Link to the fastq files in Galaxy instead of making copies.
                        This significantly speeds up SNVPhyl, but requires the Galaxy server
                        to have direct access to fastq/ directory (e.g., same filesystem) and
                        requires Galaxy to be configured with `allow_library_path_paste=True`.
                        Usage of `--deploy-docker` enables this option by default [False]
  --fastq-history-name FASTQ_HISTORY_NAME
                        Galaxy history name for previously uploaded collection of fastq files.

Output:
  --output-dir OUTPUT_DIR
                        Output directory to store results

Optional Parameters:
  --invalid-positions-file INVALID_POSITIONS_FILE
                        Tab-delimited file of positions to mask on the reference.
  --run-name RUN_NAME   Name of run added to output files [run]
  --relative-snv-abundance RELATIVE_SNV_ABUNDANCE, --snv-abundance-ratio RELATIVE_SNV_ABUNDANCE,
    --alternative-allele-ratio RELATIVE_SNV_ABUNDANCE
                        Cutoff proportion of base coverage supporting a high quality variant
                        to total coverage [0.75]
  --min-coverage MIN_COVERAGE
                        Minimum coverage for calling variants [10]
  --min-mean-mapping MIN_MEAN_MAPPING
                        Minimum mean mapping quality for reads supporting a variant [30]
  --repeat-minimum-length REPEAT_MINIMUM_LENGTH
                        Minimum length of repeat regions to remove [150]
  --repeat-minimum-pid REPEAT_MINIMUM_PID
                        Minimum percent identity to identify repeat regions [90]
  --filter-density-window FILTER_DENSITY_WINDOW
                        Window size for identifying high-density SNV regions [500]
  --filter-density-threshold FILTER_DENSITY_THRESHOLD
                        SNV threshold for identifying high-density SNV regions [2]

Additional Information:
  --version             show program's version number and exit

Example:
  bin/snvphyl.py --deploy-docker --fastq-dir fastqs/ --reference-file reference.fasta --min-coverage 5 --output-dir output

    Runs default SNVPhyl pipeline in a Docker container with the given input files,
    setting the minimum coverage for calling a SNV to 5.

  bin/snvphyl.py --galaxy-url http://galaxy --galaxy-api-key 1234abcd --fastq-dir fastqs/ --reference-file reference.fasta --output-dir output

   Runs SNVPhyl pipeline against the given Galaxy server, with the given API key,
   and by uploading the passed fastq files and reference genome (assumes workflow has been uploaded ahead of time).

  bin/snvphyl.py --galaxy-url http://galaxy --galaxy-api-key 1234abcd --fastq-history-name fastq-history --reference-file reference.fasta --output-dir output

    Runs SNVPhyl pipeline against the given Galaxy server, with the given API key,
    using structured fastq data (paired or single dataset collections) from a history with the given name.
```

# Citation

Petkau A, Mabon P, Sieffert C, Knox N, Cabral J, Iskander M, Iskander M, Weedmark K, Zaheer R, Katz L, Nadon C, Reimer A, Taboada E, Beiko R, Hsiao W, Brinkman F, Graham M, Van Domselaar G. [SNVPhyl: a single nucleotide variant phylogenomics pipeline for microbial genomic epidemiology](http://dx.doi.org/10.1099/mgen.0.000116). 08/06/2017. *M Gen* 3(6): doi:[10.1099/mgen.0.000116](https://doi.org/10.1099/mgen.0.000116).

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
[Docker Install]: https://docs.docker.com/installation/
[Galaxy Docker]: https://github.com/bgruening/docker-galaxy-stable/
[SNVPhyl Output]: http://snvphyl.readthedocs.org/en/latest/user/output/
[SNVPhyl Galaxy]: http://snvphyl.readthedocs.org/en/latest/install/galaxy/#import-snvphyl-galaxy-workflows
[Docker volume documentation]: https://docs.docker.com/engine/tutorials/dockervolumes/
