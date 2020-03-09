# Changes

## 1.4

* Updated script to be compatible with Python 2 and 3 (thanks @fmaguire).
* Added `--copy-fastq-files-to-docker` as a command-line option to disable linking to fastq files in Docker (in case of issues with links between Docker and host system).
* Added `--docker-other-options` as an option to pass command-line options directly to `docker`.

## 1.3

* Added `--docker-cpus` enabling control over the maximum number of cpus Docker will use when running SNVPhyl.
* Added `--fastq-files-as-links` which will link to fastq files in Galaxy instead of making a copy.  This drastically reduces both runtime and storage requirements, but requires Galaxy server to have access to the same filesystem as the local machine.
  * This is enabled by default when using Docker, but required small updates to all the SNVPhyl Docker images to enable linking to files in Galaxy.

## 1.2

* Added additional timing measurements.
* Added `--relative-snv-abundance` as the default name for `--snv-abundance-ratio` and `--alternative-allele-ratio` (both previous names work the same).

## 1.1

* Added SNVPhyl workflow version `1.0.1`.
* Added functionality to download existing files from Galaxy in the case of an error occuring with the workflow.
* Added `--snv-abundance-ratio` as an alternative name for the `--alternative-allele-ratio` parameter.

## 1.0.0

* Initial release.
* Ability to launch multiple versions (`1.0`, `0.3`, `0.2-beta-1`) of the SNVPhyl pipeline from the command-line into either an external Galaxy instance or Docker container.
