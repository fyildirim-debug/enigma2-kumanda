#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kumanda kod haritasini kalici olarak kurar.  ALICIDA calisir.

NE YAPAR
--------
1. Keymap dosyasini ve yukleyiciyi /etc/ altina kopyalar
2. Her acilista calisacak init scriptini olusturur
3. Yuklemeyi hemen uygular, sonucu dogrular

Kernel'e yazilan tus haritasi bellekte tutulur ve cihaz kapaninca kaybolur.
Bu yuzden acilista yeniden yazilmasi gerekir; init scripti bunu yapar ve
rcS.d/rc3.d'ye S99 olarak baglanir - yani Enigma2 baslamadan hemen once.

KULLANIM
--------
    python3 kur.py                                  varsayilan keymap
    python3 kur.py --keymap keymaps/next_innova_4k.keymap
    python3 kur.py --kaldir                          kurulumu geri alir

Ornek akis:
    # dosyalari aliciya kopyala (FTP ile /tmp/kumanda/ altina)
    cd /tmp/kumanda
    python3 kur.py --keymap keymaps/next_innova_4k.keymap
"""

import os
import sys
import shutil
import subprocess

KOK = os.path.dirname(os.path.abspath(__file__))

KEYMAP_YOL = "/etc/next_innova.keymap"
YUKLEYICI_YOL = "/etc/next_kumanda_yukle.py"
INIT_YOL = "/etc/init.d/next-kumanda"
BAGLAR = ("/etc/rcS.d/S99next-kumanda", "/etc/rc3.d/S99next-kumanda")

VARSAYILAN_KEYMAP = os.path.join(KOK, "keymaps", "next_innova_4k.keymap")
YUKLEYICI_KAYNAK = os.path.join(KOK, "kumanda_yukle.py")


INIT = '''#!/bin/sh
### BEGIN INIT INFO
# Provides:          next-kumanda
# Required-Start:    $local_fs
# Default-Start:     S 2 3 4 5
# Short-Description: Kumanda kod haritasini kernel keymap'ine yukler
### END INIT INFO

# Kernel'in tus haritasi bellekte tutulur, her acilista yeniden yazilmali.
case "$1" in
  start|"")
    [ -f %(yukleyici)s ] && \\
      python3 %(yukleyici)s %(keymap)s > /var/log/next-kumanda.log 2>&1
    ;;
esac
exit 0
''' % {"yukleyici": YUKLEYICI_YOL, "keymap": KEYMAP_YOL}


def bilgi(m):
    print("  " + m, flush=True)


def basarili(m):
    print("  [+] " + m, flush=True)


def hata(m):
    print("  [!] " + m, flush=True)


def kabuk(komut):
    try:
        s = subprocess.run(komut, shell=True, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, timeout=90)
        return s.stdout.decode("utf-8", "replace")
    except Exception as e:
        return str(e)


def kur(keymap_kaynak):
    print()
    print("  Kumanda kod haritasi kurulumu")
    print("  " + "-" * 42)

    if os.geteuid() != 0:
        hata("root olarak calistirilmali")
        return 1

    if not os.path.exists(keymap_kaynak):
        hata("keymap bulunamadi: %s" % keymap_kaynak)
        return 1
    if not os.path.exists(YUKLEYICI_KAYNAK):
        hata("kumanda_yukle.py bulunamadi: %s" % YUKLEYICI_KAYNAK)
        return 1

    shutil.copyfile(keymap_kaynak, KEYMAP_YOL)
    shutil.copyfile(YUKLEYICI_KAYNAK, YUKLEYICI_YOL)
    os.chmod(YUKLEYICI_YOL, 0o755)
    basarili("keymap ve yukleyici /etc/ altina kopyalandi")

    with open(INIT_YOL, "w", encoding="utf-8", newline="\n") as f:
        f.write(INIT)
    os.chmod(INIT_YOL, 0o755)
    for bag in BAGLAR:
        kabuk("ln -sf ../init.d/next-kumanda " + bag)
    basarili("acilis scripti kuruldu (rcS.d + rc3.d, S99)")

    cikti = kabuk("python3 %s %s" % (YUKLEYICI_YOL, KEYMAP_YOL))
    print()
    for satir in cikti.strip().split("\n"):
        bilgi(satir)
    print()

    if "yazilan" in cikti and "tamam" in cikti:
        basarili("kumanda tanitildi ve kalici hale getirildi")
        print()
        print("  Tuslar calismiyorsa Enigma2'yi bir kez yeniden baslat:")
        print("      init 4; sleep 5; init 3")
        print()
        return 0

    hata("yukleme basarisiz - ciktiya bak")
    return 1


def kaldir():
    print()
    print("  Kumanda kurulumu kaldiriliyor")
    print("  " + "-" * 42)

    for yol in list(BAGLAR) + [INIT_YOL, YUKLEYICI_YOL, KEYMAP_YOL]:
        try:
            os.unlink(yol)
        except OSError:
            pass
    basarili("dosyalar ve acilis baglari silindi")
    bilgi("kernel'deki harita bir sonraki acilista sifirlanir")
    print()
    return 0


def main():
    argv = sys.argv[1:]

    if "--kaldir" in argv:
        return kaldir()

    keymap = VARSAYILAN_KEYMAP
    if "--keymap" in argv:
        i = argv.index("--keymap")
        if i + 1 < len(argv):
            keymap = argv[i + 1]
            if not os.path.isabs(keymap):
                keymap = os.path.join(os.getcwd(), keymap)

    try:
        return kur(keymap)
    except KeyboardInterrupt:
        print()
        hata("iptal edildi")
        return 1


if __name__ == "__main__":
    sys.exit(main())
