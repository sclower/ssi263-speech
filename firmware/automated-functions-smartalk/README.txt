SmarTalk software -- S_TALK.EXE, Automated Functions' own, unmodified
=======================================================================

The SmarTalk host (src/hosts/smartalk.py, and src/csrc/smartalk/st_host.c, the same in C) runs Automated Functions'
own DOS text-to-speech TSR for the box, version 1.21 (1995-11-15):

  S_TALK.EXE   36,882 bytes   sha256 6cef7bc467959960505bfd771d07f387b7bdfad25bad2b51801ae56bb8d78e6c

That is the conventional-memory TSR from the SmarTalk V1.21 disk, as it is on the disk (the same disk is in the
vintage-access archive, under "Automated Functions").  The host does ST_RUN.EXE's part itself; XS_TALK.EXE (the XMS
version) is not used.

Its notice -- this file is NOT under the repository's MIT licence:

  S_TALK.EXE is Copyright 1995, Automated Functions, Inc., All rights reserved.

  The disk's README.TXT says: "Please feel free to share the new version of the SmarTalk software with anyone who
  needs it."

It is shared here on those words, unchanged: never patch it.  Only S_TALK.EXE is included; the disk's other files are
not (INI3.EXE and SSIL.DLL are not Automated Functions' own).  The NVDA add-on carries it with this notice
(nvda/build_ssi263.py), and so do the SAPI voices, the Linux package and the GitHub Android APK (in assets/smartalk;
src/platforms/android/test/check_apk_no_firmware.py lets exactly it through there).  The Apple apps do not: they
stay free of firmware, and the file is imported there like the others
(src/platforms/apple/test/check_archive_no_firmware.py refuses it by its sha256).
