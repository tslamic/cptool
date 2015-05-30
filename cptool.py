import argparse
import datetime
import zipfile
import filecmp
import shutil
import sys
import os

REPO = os.path.expanduser("~/.cptool")
BACKUP = ".cpbackup"
SYNC = ".cpsync"

DATETIME_FORMAT = "%a_%b_%d_%Y_%H_%M_%S_%f"
SEPARATOR = "_on_"


# Helpers


def check_dir(directory, message=None):
    if not os.path.isdir(directory):
        if message is None:
            message = "Directory '%s' does not exist." % directory
        raise CpException(message)


def encode_dir_name(directory):
    path = directory.replace(os.path.sep, '_')
    when = datetime.datetime.now().strftime(DATETIME_FORMAT)
    return path + SEPARATOR + when


def decode_dir_name(name):
    base = os.path.splitext(name)[0]
    path, when = base.split(SEPARATOR)
    path = path.replace("_", os.path.sep)
    when = datetime.datetime.strptime(when, DATETIME_FORMAT)
    return path, when


def read(prompt=None, converter=None):
    if prompt is not None:
        sys.stdout.write(prompt)
    user_input = sys.stdin.read(1)
    return user_input if converter is None else converter(user_input)


class CpException(Exception):
    pass


# Backup & revert


def backup(directory):
    if not os.path.isdir(REPO):
        os.makedirs(REPO)
    assert os.path.isdir(REPO)
    name = encode_dir_name(directory)
    archive_path = os.path.join(REPO, name)
    assert not os.path.isfile(archive_path)
    shutil.make_archive(archive_path, "zip", directory)
    backup_path = os.path.join(directory, BACKUP)
    with open(backup_path, 'w') as b:
        b.write(name)
    assert os.path.getsize(backup_path) == len(name)


def get_archive_name(directory):
    assert os.path.isdir(directory)
    backup_path = os.path.join(directory, BACKUP)
    if not os.path.isfile(backup_path):
        raise CpException("Backup file missing in '%s'." % directory)
    with open(backup_path) as b:
        archive_name = b.readline()
        assert archive_name
        return archive_name + ".zip"


def revert(directory, archive_name=None):
    check_dir(directory)
    if archive_name is None:
        archive_name = get_archive_name(directory)
    assert archive_name
    archive_path = os.path.join(REPO, archive_name)
    if not os.path.isfile(archive_path):
        raise CpException("Archive '%s' unavailable." % archive_path)
    shutil.rmtree(directory)
    with zipfile.ZipFile(archive_path) as zf:
        zf.extractall(directory)


def backup_history(directory):
    check_dir(directory)
    history = []
    try:
        archive_name = get_archive_name(directory)
    except CpException:
        return history
    has_history = True
    while has_history:
        archive_path = os.path.join(REPO, archive_name)
        history.append((archive_path, os.path.getctime(archive_path)))
        with zipfile.ZipFile(archive_path) as zf:
            if BACKUP in zf.namelist():
                archive_name = zf.read(BACKUP) + ".zip"
            else:
                has_history = False
    return history


# Diffs


def find_diff(src, dst):
    if os.path.isdir(dst):
        diff = filecmp.dircmp(src, dst)
        return diff.left_only + diff.diff_files
    else:
        return [f for f in os.listdir(src)]


def apply_diff(src, dst, diff_list=None, auto_backup=True):
    if diff_list is None:
        diff_list = find_diff(src, dst)
    if diff_list:
        if auto_backup:
            backup(dst)
        for item in diff_list:
            src_item = os.path.join(src, item)
            dst_item = os.path.join(dst, item)
            if os.path.isdir(src_item):
                shutil.copytree(src_item, dst_item)
            else:
                shutil.copy(src_item, dst_item)


# User interaction


def exec_diff(src, dst):
    diff_list = find_diff(src, dst)
    if diff_list:
        print "\n".join(diff_list)
        sys.stdout.write("\nCopy all (y/n)? ")
        confirm = sys.stdin.read(1)
        if "y" == confirm.lower():
            apply_diff(src, dst, diff_list)
        else:
            print "Nothing copied."
    else:
        print "No changes found."


def manual_revert():
    check_dir(REPO, "Backup repository does not exist.")
    backup_list = filter(lambda f: f.endswith(".zip"), os.listdir(REPO))
    if not backup_list:
        raise CpException("Backup repository is empty.")
    print "Manual reverts available for:\n"
    for index, item in enumerate(backup_list):
        path, when = decode_dir_name(item)
        print "%d: %s, backed on %s" % (index, path, when)
    index = read("\nSelect backup index to apply: ", int)
    if 0 <= index < len(backup_list):
        archive_path = backup_list[index]
        path, unused_when = decode_dir_name(archive_path)
        revert(path, archive_path)
    else:
        raise CpException("Invalid selection")


# Sync


def generate_sync_file(directory, sources):
    assert os.path.isdir(directory) and len(sources) > 0
    for source in sources:
        check_dir(source, "Invalid source dir: '%s'." % source)
    absolute_paths = [os.path.abspath(s) for s in sources]
    sync_file = os.path.join(directory, SYNC)
    with open(sync_file, "w") as cp:
        cp.writelines(absolute_paths)
    assert os.path.getsize(sync_file) > 0


def sync(directory):
    sync_path = os.path.join(directory, SYNC)
    if not os.path.isfile(sync_path):
        raise CpException("Sync file for '%s' missing." % directory)
    with open(sync_path) as s:
        src_list = s.read().splitlines()
    if not src_list:
        raise CpException("Sync file is empty.")
    for src in src_list:
        check_dir(src, "Invalid source dir: '%s'." % src)
    backup(directory)
    for src in src_list:
        apply_diff(src, directory, auto_backup=False)


# CLI


class ValidDirAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        directories = values if isinstance(values, list) else [values]
        for d in directories:
            if not (os.path.isdir(d) and os.access(d, os.W_OK)):
                raise argparse.ArgumentError(self, "Invalid dir: %s" % d)
        setattr(namespace, self.dest, values)


def diff_parser():
    parser = argparse.ArgumentParser(
        description="Compare and copy missing files from one dir to another"
    )
    subparsers = parser.add_subparsers(title="Options", dest="opt")

    cp = subparsers.add_parser("cp", help="Copy from one dir to another")
    cp.add_argument("src", help="source dir", action=ValidDirAction)
    cp.add_argument("dst", help="destination dir", action=ValidDirAction)

    rv = subparsers.add_parser("rv", help="Revert")
    rv.add_argument("dir", help="dir to revert", action=ValidDirAction)

    subparsers.add_parser("manrv", help="Manual revert")

    sync = subparsers.add_parser("sync", help="Auto-sync")
    sync.add_argument("dir", help="dir to sync", action=ValidDirAction)

    mksync = subparsers.add_parser("mksync", help="Generate auto-sync folder")
    mksync.add_argument("dir", help="dir to auto-sync", action=ValidDirAction)
    mksync.add_argument("src", nargs='+', help="source dirs",
                        action=ValidDirAction)

    return parser


if __name__ == '__main__':
    h = backup_history("/Users/tslamic/Documents/Development/c")
    for path, when in h:
        print "%s : %s" % (path, datetime.datetime.fromtimestamp(when))

        # args = diff_parser().parse_args()
        # {
        #     "cp": lambda: exec_diff(args.src, args.dst),
        #     "rv": lambda: revert(args.dir),
        #     "manrv": lambda: manual_revert(),
        #     "sync": lambda: sync(args.dir),
        #     "mksync": lambda: generate_sync_file(args.dir, args.src),
        # }[args.opt]()
