import argparse
import hashlib
import zipfile
import filecmp
import shutil
import time
import sys
import os

from os.path import join, isdir

HOME = os.path.expanduser("~")
CPTOOL = ".cptool"
BACKUP_REPO = join(HOME, CPTOOL)
FORMAT = "zip"
EXTENSION = ".zip"


def backup(directory):
    if not isdir(BACKUP_REPO):
        os.makedirs(BACKUP_REPO)
    sha = hashlib.sha1(str(time.time()) + directory).hexdigest()
    shutil.make_archive(join(BACKUP_REPO, sha), FORMAT, directory)
    with open(join(directory, CPTOOL), 'w') as cp:
        cp.write(sha)


def revert(directory):
    try:
        with open(join(directory, CPTOOL)) as cp:
            sha = cp.readline()
        if os.listdir(directory):
            shutil.rmtree(directory)
        with zipfile.ZipFile(join(BACKUP_REPO, sha + EXTENSION)) as zf:
            zf.extractall(directory)
    except IOError:
        print "Either no history is available or the backup files are missing."


def find_diff(src, dst):
    if os.path.isdir(dst):
        diff = filecmp.dircmp(src, dst)
        return diff.left_only + diff.diff_files
    else:
        return [f for f in os.listdir(src)]


def copy_diff(src, dst, diff_list):
    backup(dst)
    for item in diff_list:
        src_item = join(src, item)
        dst_item = join(dst, item)
        if isdir(src_item):
            shutil.copytree(src_item, dst_item)
        else:
            shutil.copy(src_item, dst_item)


def exec_diff(src, dst):
    diff_list = find_diff(src, dst)
    if diff_list:
        print "\n".join(diff_list)
        sys.stdout.write("\nCopy all (y/n)? ")
        confirm = sys.stdin.read(1)
        if "y" == confirm.lower():
            copy_diff(src, dst, diff_list)
        else:
            print "Nothing copied."
    else:
        print "No changes found."


class DirAction(argparse.Action):
    def __call__(self, parser, namespace, values, option_string=None):
        if not os.path.isdir(values):
            raise argparse.ArgumentTypeError("not a dir: %s" % values)
        if not os.access(values, os.W_OK):
            raise argparse.ArgumentTypeError("dir not writable: %s" % values)
        setattr(namespace, self.dest, values)


def diff_parser():
    parser = argparse.ArgumentParser(
        description="Compare and copy missing files from one dir to another"
    )
    subparsers = parser.add_subparsers(title="Options", dest="opt")

    cp = subparsers.add_parser("cp", help="Copy from one dir to another")
    cp.add_argument("src", help="source dir", action=DirAction)
    cp.add_argument("dst", help="destination dir", action=DirAction)

    rv = subparsers.add_parser("rv", help="Revert cp command")
    rv.add_argument("dst", help="destination dir", action=DirAction)

    return parser


if __name__ == '__main__':
    args = diff_parser().parse_args()
    {
        "cp": lambda: exec_diff(args.src, args.dst),
        "rv": lambda: revert(args.dst)
    }[args.opt]()
