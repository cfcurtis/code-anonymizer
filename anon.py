import sys, os
from pathlib import Path
import logging
import zipfile
import shutil
import datetime
import filecmp
import argparse

from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# Global constants and singletons
TEMP_DIR = Path("temp")
ENTITIES = ["EMAIL_ADDRESS", "PERSON", "STUDENT_ID"]
OPERATORS = {
    "PERSON": OperatorConfig("replace", {"new_value": "<NAME>"}),
    "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "anon@mtroyal.ca"}),
    "STUDENT_ID": OperatorConfig("replace", {"new_value": "00000000"}),
}

# The analyzer and anonymizer engines are singletons, should be created once and reused
analyzer = AnalyzerEngine()

# define custom recognizer for student ID (9 digits)
id_pattern = Pattern(name="student_id_pattern", regex="\d{8,10}", score=0.5)
id_recognizer = PatternRecognizer(supported_entity="STUDENT_ID", patterns=[id_pattern])
analyzer.registry.add_recognizer(id_recognizer)
anonymizer = AnonymizerEngine()
logger = logging.getLogger(__name__)


def anonymize(text: str, entities: list = ENTITIES, operators: dict = OPERATORS) -> str:
    """Do the actual text anonymization"""
    try:
        results = analyzer.analyze(text=text, language="en", entities=entities)
        anonymized_text = anonymizer.anonymize(
            text=text, analyzer_results=results, operators=operators
        )
    except Exception as e:  # I'm not sure what kind of exception to expect here
        logger.error(f"Anonymization failed: {e}")
        raise e

    return anonymized_text.text


def anonymize_file(src: str, dest: str) -> bool:
    """
    Read a file from src, anonymize the contents, write to dest.
    Returns True if successful, False otherwise.
    """
    try:
        with open(src, "r") as f:
            text = f.read()
    except IOError as e:
        logger.error(f"Error reading file: {e}")
        return False

    success = True
    # go line by line and only anonymize comments
    multiline_comment = False
    anonymized_text = ""
    for line in text.split("\n"):
        if "/*" in line:
            multiline_comment = True
        if multiline_comment or line.strip().startswith("//"):
            try:
                line = anonymize(line)
            except Exception as e:
                # let it slide, but note that something failed
                success = False

        if "*/" in line:
            multiline_comment = False

        # either way, append the line
        anonymized_text += line + "\n"

    try:
        with open(dest, "w") as f:
            f.write(anonymized_text)
    except IOError as e:
        logger.error(f"Error writing file: {e}")
        return False

    return success


def process_archive(root: str, file: str, dest_root: str, exclude: list) -> int:
    """
    Unpack the jar/zip to a temp directory and anonymize any java files.
    Compares source code to any included source files in the parent directory,
    does not copy from jar if the files are the same.

    Returns the number of files anonymized without error.
    """

    jar_name = file.replace(".", "_")
    with zipfile.ZipFile(root / file, "r") as z:
        z.extractall(TEMP_DIR / jar_name)

    # go through the unpacked files and delete any that already exist
    for temp_root, _, files in os.walk(TEMP_DIR / jar_name):
        temp_root = Path(temp_root)
        for file in files:
            if not file.endswith(".java"):
                continue
            jarred_file = temp_root / file
            uncorked_file = root / file

            if uncorked_file.exists() and filecmp.cmp(
                jarred_file, uncorked_file, shallow=False
            ):
                # the files are the same, delete the temp file
                os.remove(jarred_file)

    # finally, anonymize any remaining java files from the jar
    n_processed = copy_and_anon(TEMP_DIR / jar_name, dest_root / jar_name, exclude)
    # recursively delete temp unpacked files
    shutil.rmtree(TEMP_DIR / jar_name)
    return n_processed


def copy_and_anon(src: str, dest: str, exclude: list) -> int:
    """
    Walk a directory and anonymize all java files in it, saving to destination.
    Jar files are unpacked and any source files are also anonymized, then repacked.
    Other file types (data files, .class files, word documents, etc) are not copied.

    Returns the number of files anonymized without error.
    """
    n_processed = 0
    for root, dirs, files in os.walk(src):
        root = Path(root)

        # create the same directory structure in dest, skipping over
        # anything that isn't likely to contain student code (lib, bin, etc)
        dest_root = Path(dest) / root.relative_to(src)
        dest_root.mkdir(exist_ok=True)
        for dir in dirs:
            ldir = dir.lower()
            if any([x in ldir for x in exclude]):
                dirs.remove(dir)
                continue
            dest_dir = dest_root / dir
            dest_dir.mkdir(exist_ok=True)

        # go through the files and look for java or archives
        for file in files:
            # skip over excluded files
            lfile = file.lower()
            if any([x in lfile for x in exclude]):
                continue

            if file.endswith(".java"):
                # anonymize the file and write to dest
                src_file = root / file
                dest_file = dest_root / file
                if anonymize_file(src_file, dest_file):
                    n_processed += 1

            elif file.endswith(".jar") or file.endswith(".zip"):
                n_processed += process_archive(root, file, dest_root, exclude)
            else:
                # don't copy the file
                logger.info(f"Skipping {root / file}, not java source code")

    # clean up any empty directories
    for root, dirs, files in os.walk(dest, topdown=False):
        for dir in dirs:
            if not os.listdir(Path(root) / dir):
                os.rmdir(Path(root) / dir)

    return n_processed


def main() -> None:
    """
    Create the temp directory, set up logging, then start chewing through files.
    """

    default_exclude = "lib,bin,build,dist,junit,hamcrest,checkstyle,gson"
    parser = argparse.ArgumentParser(
        description="Anonymize comments in student coding assignments (in Java)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("src", help="The root of all assignments to anonymize")
    parser.add_argument(
        "dest", help="The name of the directory to save the anonymized versions"
    )
    parser.add_argument(
        "-x",
        "--exclude",
        help="A comma-separated list of directory or jar filenames to exclude (case-insensitive, partial match)",
        default=default_exclude,
    )
    parser.add_argument("-a", "--append", help="Append excluded directories instead of replacing", action="store_true")

    args = parser.parse_args()

    if args.append:
        args.exclude = default_exclude + "," + args.exclude

    TEMP_DIR.mkdir(exist_ok=True)
    dest_dir = Path(args.dest)
    dest_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        format="%(levelname)s: %(message)s",
        filename=dest_dir / "codeanon.log",
        encoding="utf-8",
        level=logging.INFO,
    )
    logger.info(f"Anonymizing {args.src} to {args.dest}")
    logger.info(f"Start time: {datetime.datetime.now()}")
    print("Anonymizing code, this may take a while...")

    n_anon = copy_and_anon(args.src, dest_dir, args.exclude.lower().split(","))

    logger.info(f"End time: {datetime.datetime.now()}")
    print(f"{n_anon} anonymized files written to {args.dest}")

    # clean up the temp directory, should be empty at this point
    TEMP_DIR.rmdir()


if __name__ == "__main__":
    main()
