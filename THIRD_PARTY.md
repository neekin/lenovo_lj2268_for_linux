# Third-party components and provenance

- Project-maintained installer, documentation and filter changes are distributed with the repository's MIT license. Earlier repository history is retained in Git.
- `source/jbigkit/` contains JBIG-KIT 2.1 by Markus Kuhn. Its source headers specify **GPL-2.0-or-later**; the full license is preserved at `source/jbigkit/COPYING`. This is a separate license from the project's own MIT code. The bundled/native shared library incorporates that code; source and copyright notices are provided with it. The MIT file does not relicense JBIG-KIT.
- `source/lhpl_jbig_wrap.c` is the small native wrapper used by the Python filter. The complete wrapper and library sources required to rebuild the `.so` are included.
- `ppd/Lenovo-LJ2268.ppd` comes from the working device configuration derived from Lenovo's device description, with the CUPS filter reference adapted. It is not an official Lenovo-supported Linux driver. This notice does not assign MIT to third-party vendor material.
- `prebuilt/linux-armv7-glibc/libjbigwrap.so` is the saved library from the tested Linux ARMv7 device; it must accompany the corresponding source and JBIG-KIT license.
- No Windows/macOS executable driver, printer administrator password, private certificate, personal print spool, or firmware image is included.
- The optional Docker image builds on `anujdatar/cups`; that image and the Debian packages it contains retain their own licenses.
