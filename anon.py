import os, sys
from pathlib import Path
import logging
import zipfile
import shutil
import datetime
import argparse

from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# Global constants and singletons
ENTITIES = ["EMAIL_ADDRESS", "PERSON", "STUDENT_ID"]
OPERATORS = {
    "PERSON": OperatorConfig("replace", {"new_value": "<NAME>"}),
    "EMAIL_ADDRESS": OperatorConfig("replace", {"new_value": "anon@mtroyal.ca"}),
    "STUDENT_ID": OperatorConfig("replace", {"new_value": "00000000"}),
}

# The analyzer and anonymizer engines are singletons, should be created once and reused
analyzer = AnalyzerEngine()

# define custom recognizer for student ID (9 digits)
id_pattern = Pattern(name="student_id_pattern", regex=r"\d{8,10}", score=0.5)
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
        with open(src, "r", encoding="UTF-8") as f:
            text = f.read()
    except Exception as e:
        try:
            with open(src, "r", encoding="cp1252") as f:
                text = f.read()
        except Exception as e:
            logger.error(f"Error reading file {src}: {e}")
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
        with open(dest, "w", encoding="UTF-8") as f:
            f.write(anonymized_text)
    except IOError as e:
        logger.error(f"Error writing file: {e}")
        return False

    return success


def already_exists(student_root: str, filename: str) -> bool:
    """
    Check if a file already exists in the student's directory.
    """
    return (Path(student_root) / filename).exists()


def is_excluded(filename: Path, exclude: list) -> bool:
    """
    Check if a file should be excluded based on the exclude list.
    """
    filename = str(filename)
    return any([x in filename.lower() for x in exclude]) or not filename.endswith(
        (".java", ".jar", ".zip")
    )

def unpack_in_place(archive: Path) -> str:
    """
    Unpacks the jar/zip in place, returns the new directory name if successful (None otherwise).
    """
    jar_name = Path(str(archive).replace(".", "_"))
    try:
        with zipfile.ZipFile(archive, "r") as z:
            z.extractall(jar_name)
    except zipfile.BadZipFile as e:
        logger.warning(f"Could not unzip {archive}, skipping: {e}")
        return None
    
    return jar_name

def process_archive(root: Path, archive: str, submit_root: dict, exclude: list) -> int:
    """
    Unpack the jar/zip in place and anonymize any java files that aren't already in the
    submission destination directory.

    Returns the number of files anonymized without error.
    """
    jar_name = unpack_in_place(root / archive)
    if not jar_name:
        return 0

    # anonymize the files in the jar, if they aren't already in the student's directory
    n_processed = 0
    for jar_root, _, files in os.walk(jar_name):
        jar_root = Path(jar_root)
        for file in files:
            # skip over excluded files
            if is_excluded(str(jar_root / file), exclude):
                continue

            # recursively unpack nested archives
            if file.endswith(".jar") or file.endswith(".zip"):
                n_processed += process_archive(jar_root, file, submit_root, exclude)
            else:  # process java files
                if already_exists(submit_root["dest"], file):
                    logger.info(f"Skipping {jar_root / file}, already exists")
                else:
                    src_file = jar_root / file
                    dest_file = submit_root["dest"] / file
                    if anonymize_file(src_file, dest_file):
                        n_processed += 1

    # recursively delete temp unpacked files
    shutil.rmtree(jar_name)
    return n_processed

def unpack_assignments(src: Path, submit_level: int) -> list:
    """
    Unpack everything in place up to the submission level. Return the list of directories
    created for subsequent cleanup.
    """
    dirs = []
    for root, _, files in os.walk(src):
        root = Path(root)
        level = len(root.relative_to(src).parents)
        if level < submit_level:
            # go through the files and look for archives
            for file in files:
                if file.endswith(".jar") or file.endswith(".zip"):
                    jar_name = unpack_in_place(root / file)
                    if jar_name:
                        dirs.append(jar_name)

    return dirs


def copy_and_anon(args: argparse.Namespace) -> int:
    """
    Walk a directory look for submissions at the given level. Anonymize any java files found
    and write them to the anonymized submission directory as a flat structure.
    Jar files are unpacked and any source files are also anonymized if they don't already exist.
    Other file types (data files, .class files, word documents, etc) are not copied.

    Returns the number of files anonymized without error.
    """
    n_processed = 0
    submit_num = 0
    submit_root = None
    temp_unpacked = unpack_assignments(Path(args.src), args.level)

    for root, _, files in os.walk(args.src):
        root = Path(root)
        # now go through the files and look for java or archive files
        for file in files:
            if is_excluded(root / file, args.exclude):
                continue

            if submit_root and submit_root["src"] not in str(root):
                # we've moved out of the student's directory, reset to None
                submit_root = None

            # The first time we hit a directory or archive at the submit level, create a new anonymous directory.
            level = len(root.relative_to(args.src).parents)
            if not submit_root and level == args.level:
                submit_root = {"src": str(root), "dest": ""}
                named_path = Path(args.dest) / root.relative_to(args.src)
                # rename the last directory to anonymous submission counter
                submit_root["dest"] = named_path.parent / f"submission_{submit_num:02d}"
                submit_num += 1
                # create the anonymized directory
                submit_root["dest"].mkdir(exist_ok=True, parents=True)
                logger.info(f"Found new submission directory, creating {submit_root['dest']}")
            elif not submit_root and level == args.level - 1:
                # could be zip files at the submission level
                submit_root = {"src": str(root / file), "dest": Path(args.dest) / root.relative_to(args.src) / f"submission_{submit_num:02d}"}
                submit_num += 1
                submit_root["dest"].mkdir(exist_ok=True, parents=True)
                logger.info(f"Found file at expected submission level, creating {submit_root['dest']}")

            # if we've already created the submission directory, process the files
            if submit_root:
                if file.endswith(".java"):
                    if already_exists(submit_root["dest"], file):
                        logger.info(f"Skipping {root / file}, already exists")
                    else:
                        # anonymize the file and write to dest
                        src_file = root / file
                        dest_file = Path(submit_root["dest"]) / file
                        if anonymize_file(src_file, dest_file):
                            n_processed += 1

                elif file.endswith(".jar") or file.endswith(".zip"):
                    n_processed += process_archive(root, file, submit_root, args.exclude)

    # clean up any empty directories
    for root, dirs, files in os.walk(args.dest, topdown=False):
        for dir in dirs:
            if not os.listdir(Path(root) / dir):
                os.rmdir(Path(root) / dir)
    
    # clean up any temporary directories
    for temp_dir in temp_unpacked:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)

    return n_processed


def parse_args() -> argparse.Namespace:
    default_exclude = "lib,bin,build,dist,junit,hamcrest,checkstyle,gson,_MACOSX,.DS_Store,.git,.idea,.vscode,META-INF"

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
    parser.add_argument(
        "-a",
        "--append",
        help="Append excluded filenames instead of replacing",
        action="store_true",
    )
    parser.add_argument(
        "-L",
        "--level",
        help="Define the nesting level of assignment directories relative to src",
        type=int,
        default=1,
    )

    args = parser.parse_args()

    # update the global args
    if args.append:
        args.exclude = (default_exclude + "," + args.exclude).lower().split(",")
    else:
        args.exclude = args.exclude.lower().split(",")

    return args


def main() -> None:
    """
    Create the temp directory, set up logging, then start chewing through files.
    """

    args = parse_args()

    dest_dir = Path(args.dest)
    dest_dir.mkdir(exist_ok=True)
    logging.basicConfig(
        format="%(levelname)s: %(message)s",
        filename=dest_dir / "codeanon.log",
        encoding="utf-8",
        level=logging.INFO,
    )
    logger.info(f"Command: {' '.join(sys.argv)}")
    logger.info(f"Anonymizing {args.src} to {args.dest}")
    logger.info(f"Start time: {datetime.datetime.now()}")
    print("Anonymizing code, this may take a while...")

    n_anon = copy_and_anon(args)

    logger.info(f"End time: {datetime.datetime.now()}")
    print(f"{n_anon} anonymized files written to {args.dest}")


if __name__ == "__main__":
    main()
