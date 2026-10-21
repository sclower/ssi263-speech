SmarTalk software -- not included
=================================

The SmarTalk host (src/hosts/smartalk.py, and src/csrc/smartalk/st_host.c, the same in C) runs Automated Functions'
own DOS text-to-speech TSR for the box, version 1.21 (1995-11-15).  It is not in this repository.  Put your own copy
here:

  S_TALK.EXE   36,882 bytes   sha256 6cef7bc467959960505bfd771d07f387b7bdfad25bad2b51801ae56bb8d78e6c

That is the conventional-memory TSR from the SmarTalk V1.21 disk, loaded as it is.  The host does ST_RUN.EXE's part
itself; XS_TALK.EXE (the XMS version) is not used.  nvda/build_ssi263.py stages the SmarTalk unit in the 0.8 add-on
when this file is here, and leaves it out (with a note) when it is not.

The disk's README.TXT says: "Please feel free to share the new version of the SmarTalk software with anyone who needs
it."  Whether a release carries it is decided for the release.

This folder's contents are ignored by git.
