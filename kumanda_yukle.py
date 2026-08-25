#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kumanda kod haritasini kernel'in girdi surucusune yukler.

NEDEN GEREKLI
-------------
Enigma2 imajlari (OpenATV, OpenPLi, ...) genellikle baska bir marka icin
derlenmistir.  Kernel'in rc-core surucusu yalnizca o markanin kumandasinin
NEC kodlarini tanir.  Cihazin kendi kumandasi farkli bir "cihaz adresi"
kullaniyorsa alici sinyali alir ama hangi tusa karsilik geldigini bilemez;
sonucta hicbir tus calismaz.

Bu script scancode -> keycode eslemesini dogrudan girdi surucusune yazar.
`ir-keytable` araci imajlarda cogu zaman bulunmadigi icin ioctl dogrudan
cagrilir.

NASIL CALISIR
-------------
Linux'ta her girdi aygitinin bir tus haritasi vardir.  EVIOCSKEYCODE ioctl'i
bu haritaya tek tek girdi yazar:

    struct input_keymap_entry_v1 { __u32 scancode; __u32 keycode; }

Yani 8 baytlik bir yapiya iki 32-bit sayi konur.  Bu, cekirdegin "0x296247b8
kodunu gorursen bunu KEY_OK say" seklinde ogrenmesini saglar.  Yazilan
harita bellekte tutulur, cihaz kapaninca kaybolur; kalici olmasi icin her
acilista tekrar yazilmalidir (bkz. kur.py).

KULLANIM
--------
    python3 kumanda_yukle.py                       varsayilan keymap
    python3 kumanda_yukle.py benim.keymap          belirli bir dosya

Enigma2 girdi aygitini tekeline almadigi icin calisirken de yazilabilir;
yine de sorun yasanirsa once `init 4` ile durdurup sonra `init 3` ile
baslatmak en garantili yoldur.
"""

import os
import sys
import glob
import fcntl
import struct

VARSAYILAN_KEYMAP = "/etc/next_innova.keymap"


# ----------------------------------------------------------------------
# Linux tus kodlari  (input-event-codes.h)
#
# Enigma2'nin kullandigi tuslarin tamami burada.  Keymap dosyasinda bu
# isimlerden biri ya da dogrudan sayisal deger (10, 0x0A) yazilabilir.
# ----------------------------------------------------------------------

KEYCODES = {
    # temel
    "KEY_ESC": 1, "KEY_TAB": 15, "KEY_ENTER": 28, "KEY_SPACE": 57,
    "KEY_BACKSPACE": 14, "KEY_DELETE": 111, "KEY_INSERT": 110,
    "KEY_HOME": 102, "KEY_END": 107, "KEY_PAGEUP": 104, "KEY_PAGEDOWN": 109,

    # rakamlar
    "KEY_1": 2, "KEY_2": 3, "KEY_3": 4, "KEY_4": 5, "KEY_5": 6,
    "KEY_6": 7, "KEY_7": 8, "KEY_8": 9, "KEY_9": 10, "KEY_0": 11,

    # fonksiyon tuslari
    "KEY_F1": 59, "KEY_F2": 60, "KEY_F3": 61, "KEY_F4": 62, "KEY_F5": 63,
    "KEY_F6": 64, "KEY_F7": 65, "KEY_F8": 66, "KEY_F9": 67, "KEY_F10": 68,
    "KEY_F11": 87, "KEY_F12": 88,

    # gezinme
    "KEY_UP": 103, "KEY_LEFT": 105, "KEY_RIGHT": 106, "KEY_DOWN": 108,
    "KEY_OK": 352, "KEY_BACK": 158, "KEY_EXIT": 174, "KEY_MENU": 139,
    "KEY_HELP": 138, "KEY_INFO": 358, "KEY_CONTEXT_MENU": 438,

    # ses ve kanal
    "KEY_MUTE": 113, "KEY_VOLUMEDOWN": 114, "KEY_VOLUMEUP": 115,
    "KEY_CHANNELUP": 402, "KEY_CHANNELDOWN": 403,
    "KEY_NEXT": 407, "KEY_PREVIOUS": 412, "KEY_LAST": 405,

    # guc
    "KEY_POWER": 116, "KEY_POWER2": 356, "KEY_SLEEP": 142, "KEY_WAKEUP": 143,

    # oynatma
    "KEY_PLAY": 207, "KEY_PAUSE": 119, "KEY_PLAYPAUSE": 164,
    "KEY_STOP": 128, "KEY_RECORD": 167,
    "KEY_REWIND": 168, "KEY_FASTFORWARD": 208,
    "KEY_NEXTSONG": 163, "KEY_PREVIOUSSONG": 165,
    "KEY_EJECTCD": 161,

    # renkli tuslar
    "KEY_RED": 398, "KEY_GREEN": 399, "KEY_YELLOW": 400, "KEY_BLUE": 401,

    # yayin / medya
    "KEY_TV": 377, "KEY_TV2": 378, "KEY_VCR": 379, "KEY_VCR2": 380,
    "KEY_SAT": 381, "KEY_SAT2": 382, "KEY_CD": 383, "KEY_TAPE": 384,
    "KEY_RADIO": 385, "KEY_TUNER": 386, "KEY_PLAYER": 387, "KEY_TEXT": 388,
    "KEY_DVD": 389, "KEY_AUX": 390, "KEY_MP3": 391, "KEY_AUDIO": 392,
    "KEY_VIDEO": 393, "KEY_DIRECTORY": 394, "KEY_LIST": 395, "KEY_MEMO": 396,
    "KEY_CALENDAR": 397,

    # Enigma2'de sik kullanilanlar
    "KEY_EPG": 365, "KEY_PVR": 366, "KEY_FAVORITES": 364,
    "KEY_PROGRAM": 362, "KEY_SUBTITLE": 370, "KEY_ANGLE": 371,
    "KEY_ZOOM": 372, "KEY_MODE": 373, "KEY_KEYBOARD": 374,
    "KEY_SCREEN": 375, "KEY_VMODE": 375, "KEY_PC": 376,
    "KEY_OPTION": 357, "KEY_TIME": 353, "KEY_TITLE": 368,
    "KEY_SEARCH": 217, "KEY_BOOKMARKS": 156, "KEY_HOMEPAGE": 172,
    "KEY_VOD": 389, "KEY_ASPECT_RATIO": 375, "KEY_FULL_SCREEN": 374,
    "KEY_MEDIA": 226, "KEY_WWW": 150, "KEY_CONFIG": 171,
    "KEY_ARCHIVE": 361, "KEY_SHUFFLE": 410, "KEY_BREAK": 411,
    "KEY_DIGITS": 413, "KEY_TEEN": 414, "KEY_TWEN": 415,
}


def _IOW(tur, nr, boyut):
    """Linux _IOW makrosunun Python karsiligi."""
    return (1 << 30) | (boyut << 16) | (ord(tur) << 8) | nr


# struct { __u32 scancode; __u32 keycode; }  -> 8 bayt
EVIOCSKEYCODE = _IOW("E", 0x04, 8)


def rc_girdi_aygitlari():
    """rc-core'a (kizilotesi alici) bagli girdi aygitlarini bulur.

    /sys/class/rc/rcN/inputM/eventK yolu, hangi event aygitinin kizilotesi
    aliciya ait oldugunu soyler.  Boylece klavye ya da fare gibi baska
    aygitlara yanlislikla yazilmaz.  Yol bulunamazsa butun event
    aygitlari denenir (yazilamayanlar zaten reddedilir).
    """
    bulunan = []
    for rc in sorted(glob.glob("/sys/class/rc/rc*")):
        for inp in sorted(glob.glob(os.path.join(rc, "input*"))):
            for ev in sorted(glob.glob(os.path.join(inp, "event*"))):
                bulunan.append("/dev/input/" + os.path.basename(ev))
    return bulunan or sorted(glob.glob("/dev/input/event*"))


def keymap_oku(yol):
    """Keymap dosyasini (scancode, keycode, ad) listesine cevirir.

    Bicim - her satirda bir tus, '#' sonrasi yorum:

        0x296247b8 KEY_OK
        0x29620af5 KEY_POWER
        0x296200ff 11              # sayisal keycode de olur
    """
    girdiler = []
    with open(yol, "r", encoding="utf-8") as f:
        for satirno, satir in enumerate(f, 1):
            satir = satir.split("#")[0].strip()
            if not satir:
                continue
            parca = satir.split()
            if len(parca) < 2:
                print("  satir %d atlandi (eksik alan): %s" % (satirno, satir))
                continue

            try:
                scancode = int(parca[0], 16)
            except ValueError:
                print("  satir %d atlandi (scancode okunamadi): %s" % (satirno, satir))
                continue

            ad = parca[1]
            if ad in KEYCODES:
                keycode = KEYCODES[ad]
            else:
                try:
                    keycode = int(ad, 0)          # 10, 0x0A, 0o12 hepsi olur
                except ValueError:
                    print("  satir %d atlandi (bilinmeyen tus): %s" % (satirno, ad))
                    continue

            girdiler.append((scancode, keycode, ad))
    return girdiler


def aygita_yaz(aygit, girdiler):
    """Bir girdi aygitina keymap girdilerini yazar. -> (basarili, reddedilen)"""
    basarili = hata = 0
    fd = os.open(aygit, os.O_RDWR)
    try:
        for scancode, keycode, _ad in girdiler:
            veri = struct.pack("<II", scancode, keycode)
            try:
                fcntl.ioctl(fd, EVIOCSKEYCODE, veri)
                basarili += 1
            except OSError:
                # Aygit bu scancode'u kabul etmiyor olabilir; digerleri denenir.
                hata += 1
    finally:
        os.close(fd)
    return basarili, hata


def main():
    yol = sys.argv[1] if len(sys.argv) > 1 else VARSAYILAN_KEYMAP

    if not os.path.exists(yol):
        print("keymap dosyasi bulunamadi: %s" % yol)
        return 1

    girdiler = keymap_oku(yol)
    if not girdiler:
        print("keymap bos ya da hicbir satir okunamadi: %s" % yol)
        return 1
    print("keymap: %s  (%d tus)" % (yol, len(girdiler)))

    aygitlar = rc_girdi_aygitlari()
    if not aygitlar:
        print("girdi aygiti bulunamadi (/dev/input/event*)")
        return 1

    toplam = 0
    for aygit in aygitlar:
        try:
            ok, hata = aygita_yaz(aygit, girdiler)
        except OSError as e:
            print("%-22s acilamadi: %s" % (aygit, e))
            continue
        print("%-22s yazilan %d, reddedilen %d" % (aygit, ok, hata))
        toplam += ok

    if toplam:
        print("tamam - kumanda tanitildi")
        return 0

    print("hicbir girdi yazilamadi")
    return 1


if __name__ == "__main__":
    sys.exit(main())
