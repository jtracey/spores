#!/usr/bin/env python3

# Prints the count of prior commits from contributors to a Firefox bug
# (i.e., those who introduced it --- NOT who fixed it).
#
# Invoke with the bug number as the first argument, and it should output
# a line for each author who contributed to that bug [0] with the number
# of commits they had made prior to introducing that bug. Add a second
# argument (doesn't matter what) if you want to limit this to rust code
# (or rather, files that end in ".rs").
#
# It uses the CLI for mercurial rather than the Python API, because
# "For the vast majority of third party code, the best approach is to
# use Mercurial's published, documented, and stable API: the command
# line interface." - https://www.mercurial-scm.org/wiki/MercurialApi
#
# Unfortunately, this "stable API" appears to not be so stable after
# all, and I've had this script break between mercurial revisions. So
# it probably should be re-written using the internal API, which I'm
# guessing would simplify it considerably.
#
# [0] According to the SZZ algorithm, which I find lacking,
# but apparently not much else exists. :/

import sys
import subprocess
from shlex import quote

# pseudo-API from hg CLI commands
class HgPApi:
    def run_command(args):
        return subprocess.check_output(["hg"] + args, universal_newlines=True)
    def revs_from_keyword(keyword):
        return HgPApi.run_command(["log", "-T", "{rev} ", "--keyword", keyword]).split()
    def diffs_from_rev(rev):
        return HgPApi.run_command(["log", "-p", "-r", rev])
    def parent(rev):
        return HgPApi.run_command(["log", "-T", "{p1rev}", "-r", rev])
    def blame(filename, rev):
        return HgPApi.run_command(["annotate", "-r", rev, filename])
    def author(rev):
        return HgPApi.run_command(["log", "-T", "{author}", "-r", rev])
    def count_prior_commits(author, rev):
        # run as one external command for better performance
        author = quote(author)
        rev = str(int(rev))
        command = "hg log -T '1' --user {} -r ::{} | wc -c".format(author, rev)
        return subprocess.check_output(command, shell=True, universal_newlines=True).rstrip()

# the diff associated with a particular revision
class RevisionDiff:
    def __init__(self, revision, lines):
        self.revision = revision
        self.files = []
        for line in lines:
            if not line:
                continue
            if line.find("diff ") == 0:
                # new file
                filename = line.split()[-1][2:]
                self.files.append(FileDiff(revision, filename))
            if line[0] == '@':
                # line numbers
                comma = line.find(',', 3)
                old_line_start = int(line[4:comma])
                diff_size = int(line[comma+1:line.find(' ', 3)])
                self.files[-1].diffs.append(DiffLines(old_line_start, diff_size))

    def get_blamed_revs(self, exclude, rust_only):
        blamed_revs = set([])
        for fdiff in self.files:
            if rust_only and not fdiff.is_rust_file():
                continue
            blamed_revs |= fdiff.get_blamed_revs(exclude)
        return blamed_revs

# the diff associated with a file at a particular revision
class FileDiff:
    def __init__(self, revision, filename):
        self.revision = revision
        self.filename = filename
        self.diffs = []

    def is_rust_file(self):
        return self.filename.find(".rs",-3) != -1

    def get_blamed_revs(self, exclude):
        blamed_revs = set([])
        blame_raw = HgPApi.blame(self.filename, HgPApi.parent(self.revision))
        blame_lines = blame_raw.splitlines()
        ldi = iter(self.diffs)
        ld = next(ldi)
        for i, line in enumerate(blame_lines):
            if i >= (ld.start + ld.count):
                ld = next(ldi, None)
            if ld is None:
                break
            if i >= ld.start:
                blame_rev = line.split(":")[0]
                if blame_rev not in exclude:
                    blamed_revs.add(blame_rev)
        return blamed_revs

# the lines associated with a piece of a diff
class DiffLines:
    def __init__(self, start, count):
        # convert to 0-initialized line #s
        self.start = start-1
        self.count = count

def get_blamed_revs(rev_diffs, exclude, rust_only):
    blamed_revs = set([])
    for rev_diff in rev_diffs:
        blamed_revs |= rev_diff.get_blamed_revs(exclude, rust_only)
    return blamed_revs

def get_blamed_names(blamed_revs):
    blamed_names = { }
    while(len(blamed_revs)):
        rev = blamed_revs.pop()
        author = HgPApi.author(rev)
        if (author not in blamed_names) or (int(rev) < int(blamed_names[author])):
            blamed_names[author] = rev
    return blamed_names

def main(keyword, rust_only=False):
    revisions = HgPApi.revs_from_keyword(keyword)
    if not revisions:
        return
    # get the text of the diffs for each patch
    raw_data = [(revision, HgPApi.diffs_from_rev(revision)) for revision in revisions]
    # parse them into a format we understand
    rev_diffs = [RevisionDiff(revision, d.splitlines()) for (revision, d) in raw_data]
    # get the list of revisions that contributed to these diffs,
    # excluding these revisions themselves
    blamed_revs = get_blamed_revs(rev_diffs, revisions, rust_only)
    # get the names of the users who authored each of those revisions,
    # and associate them with the earliest contributing revision they authored
    blamed_names = get_blamed_names(blamed_revs)
    for name in blamed_names:
        commit_count = HgPApi.count_prior_commits(name, blamed_names[name])
        print(commit_count)

if __name__ == '__main__':
    main(*sys.argv[1:])
