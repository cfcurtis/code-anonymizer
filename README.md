# Code Anonymization Script
This repo contains a Python script to anonymize student code submissions. At the moment, it is hard-coded to process java files, and it only anonymizes information in comments (the most likely place for student identifying information).

## Overview
Student submissions need to be in a somewhat regular directory structure, with all submissions at the same level of nesting. Submissions may be in a directory for each student, or a zip/jar file. The level of nesting (relative to the top-level source) should be specified with the `-L` flag, which works the same way as the `tree` command.

For example, given the following structure:
```
src
├── class1
|   ├── assignment1
|   |   ├── student1
|   |   |   ├── file1.java
|   |   |   └── file2.java
|   |   └── student2
|   |   |   ├── file1.java
|   |   |   └── file2.java
|   |   └── student3.zip
|   └── assignment2
|       ├── student1.jar
|       └── student2
|           ├── file1.java
```

The level of nesting is 3 and the script should be run as:
```bash
$ code-anonymizer /path/to/src /path/to/dest -L 3
```

The output is a flat directory per student containing the anonymized java files only. Filenames are **assumed to be unique** within a student's directory, but not across students.

The script does the following:
- Creates the specified destination directory
- Walks the source tree doing the following:
   - Creates subdirectories in the destination for each submission
   - Anonymizes the **comments** in java files, then writes the anonymized file to the corresponding destination (if not already extant).
   - If a zip or jar file is encountered, it is extracted in-place, processed, then the unpacked directory is deleted. 
- Any non-java files are ignored.

## Installation and Usage
Note: this project depends on [Microsoft Presidio](https://microsoft.github.io/), which uses spaCy to detect identifying information such as names and student ids. This script will download the spaCy model `en_core_web_lg` the first time it is run, which is about 560MB.

### Using Pip
1. Clone and install with git + pip:
    ```bash
    pip install git+https://github.com/cfcurtis/code-anonymizer.git
    ```
2. Run the script with the following command:
   ```bash
   code-anonymizer <src> <dest>
   ```
   where `<src>` is the path to the root directory containing assignments, and `<dest>` is the name of a new directory to create containing the anonymized versions.

### From source
1. Clone this repo
2. Install the dependencies:
   ```bash
   pip install presidio-analyzer
   pip install presidio-anonymizer
   ```
3. Run the script with the following command:
   ```bash
   python anon.py <src> <dest>
   ```
   where `<src>` is the path to the root directory containing assignments, and `<dest>` is the name of a new directory to create containing the anonymized versions.

## Excluding Files
To exclude directories or filenames from being processed (e.g. non-student files), pass the argument `--exclude` or `-x` followed by a comma-separated list of directories or files. The default value is:

```bash
lib,bin,build,dist,junit,hamcrest,checkstyle,gson,_MACOSX,.DS_Store,.git,.idea,.vscode,META-INF
```

By default, this list will be **replaced** by any `-x` arguments. To append to the list, use the `--append` or `-a` flag.

## Argument summary
```
$ python .\anon.py -h
usage: anon.py [-h] [-x EXCLUDE] [-a] [-s] [-l LEVEL] src dest

Anonymize comments in student coding assignments (in Java)

positional arguments:
  src                   The root of all assignments to anonymize
  dest                  The name of the directory to save the anonymized versions

options:
  -h, --help            show this help message and exit
  -x EXCLUDE, --exclude EXCLUDE
                        A comma-separated list of directory or jar filenames to exclude (case-insensitive, partial match) (default:
                        lib,bin,build,dist,junit,hamcrest,checkstyle,gson,_MACOSX,.DS_Store,.git,.idea,.vscode,META-INF)
  -a, --append          Append excluded filenames instead of replacing (default: False)
  -l LEVEL, --level LEVEL
                        Define the nesting level of assignment directories (default: 3)
```