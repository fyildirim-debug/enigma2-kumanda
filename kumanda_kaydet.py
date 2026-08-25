#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Kumanda ogretme araci: tuslara basarsin, keymap dosyasi uretir.

NE ISE YARAR
------------
Elindeki kumanda bu depodaki hazir keymap'lerden birine uymuyorsa (baska
model alici, baska marka kumanda, evrensel kumanda) bu script ile kendi
keymap dosyani cikarirsin.  Script sirayla "su tusa bas" der, kumandadan
gelen ham kodu yakalar ve sonunda kumanda_yukle.py'nin okuyabilecegi bir
dosya yazar.

NASIL CALISIR
-------------
Kizilotesi alicinin girdi aygiti (/dev/input/eventN) iki tur olay uretir:

    EV_MSC / MSC_SCAN   ham scancode - kernel tanimasa bile gelir
    EV_KEY              cozulmus tus  - yalnizca keymap'te karsiligi varsa

Bu script MSC_SCAN dinler.  Boylece kernel'in hic tanimadigi tuslar da
yakalanir; zaten sorunun tamami budur.

ONEMLI
------
Enigma2 calisirken girdi aygitini kendine kilitleyebilir (EVIOCGRAB) ve
olaylar bu scripte ulasmaz.  Kayittan once Enigma2'yi durdur:

    init 4          Enigma2'yi durdurur (TV'de goruntu kesilir)
    python3 kumanda_kaydet.py
    init 3          Enigma2'yi geri baslatir

KULLANIM
--------
    python3 kumanda_kaydet.py                        rehberli kayit
    python3 kumanda_kaydet.py -o benim.keymap        cikti dosyasi
    python3 kumanda_kaydet.py --hepsi                serbest dinleme
    python3 kumanda_kaydet.py --aygit /dev/input/event1

Rehberli kayitta:
    tusa bas   -> kaydeder, sirakine gecer
    ENTER      -> o tusu atlar
    q + ENTER  -> kaydi bitirir, o ana kadar toplananlari yazar
"""

import os
import sys
import glob
import time
import select
import struct

# struct input_event { struct timeval time; __u16 type, code; __s32 value; }
# 32-bit ARM'de timeval iki long'dur -> "<llHHi" (16 bayt)
OLAY_BICIM = "<llHHi"
OLAY_BOYUT = struct.calcsize(OLAY_BICIM)

EV_KEY = 0x01
EV_MSC = 0x04
MSC_SCAN = 0x04

# Ayni tusa basili tutunca kernel tekrar uretir; bu sureden kisa
# araliklarla gelen ayni kod yok sayilir.
TEKRAR_ESIGI = 0.8


# ----------------------------------------------------------------------
# Rehberli kayitta sorulacak tuslar.
#
# (keycode adi, ekranda gorunecek aciklama)
# Sirasi Enigma2'de en cok kullanilandan basa dogru duzenlendi; istemedigin
# tusu ENTER ile atlayabilirsin.
# ----------------------------------------------------------------------

TUS_LISTESI = [
    ("KEY_POWER",       "Guc"),
    ("KEY_OK",          "OK / Enter"),
    ("KEY_UP",          "Yon: Yukari"),
    ("KEY_DOWN",        "Yon: Asagi"),
    ("KEY_LEFT",        "Yon: Sol"),
    ("KEY_RIGHT",       "Yon: Sag"),
    ("KEY_MENU",        "Menu"),
    ("KEY_EXIT",        "Cikis"),
    ("KEY_BACK",        "Geri"),
    ("KEY_INFO",        "Bilgi"),
    ("KEY_EPG",         "EPG / Yayin akisi"),
    ("KEY_VOLUMEUP",    "Ses +"),
    ("KEY_VOLUMEDOWN",  "Ses -"),
    ("KEY_MUTE",        "Sessiz"),
    ("KEY_CHANNELUP",   "Kanal +"),
    ("KEY_CHANNELDOWN", "Kanal -"),
    ("KEY_1",           "Rakam 1"),
    ("KEY_2",           "Rakam 2"),
    ("KEY_3",           "Rakam 3"),
    ("KEY_4",           "Rakam 4"),
    ("KEY_5",           "Rakam 5"),
    ("KEY_6",           "Rakam 6"),
    ("KEY_7",           "Rakam 7"),
    ("KEY_8",           "Rakam 8"),
    ("KEY_9",           "Rakam 9"),
    ("KEY_0",           "Rakam 0"),
    ("KEY_RED",         "Kirmizi"),
    ("KEY_GREEN",       "Yesil"),
    ("KEY_YELLOW",      "Sari"),
    ("KEY_BLUE",        "Mavi"),
    ("KEY_TEXT",        "Teletext"),
    ("KEY_SUBTITLE",    "Altyazi"),
    ("KEY_AUDIO",       "Ses secimi"),
    ("KEY_FAVORITES",   "Favoriler"),
    ("KEY_TV",          "TV"),
    ("KEY_RADIO",       "Radyo"),
    ("KEY_SAT",         "Uydu / Kanal listesi"),
    ("KEY_PLAYPAUSE",   "Oynat / Duraklat"),
    ("KEY_STOP",        "Durdur"),
    ("KEY_RECORD",      "Kayit"),
    ("KEY_REWIND",      "Geri sar"),
    ("KEY_FASTFORWARD", "Ileri sar"),
    ("KEY_PVR",         "Kayitlar"),
    ("KEY_SLEEP",       "Uyku"),
    ("KEY_VMODE",       "Cozunurluk / Format"),
    ("KEY_MODE",        "Mod"),
]


# ----------------------------------------------------------------------
# Aygit ve olay okuma
# ----------------------------------------------------------------------

def rc_aygitlari():
    """Kizilotesi aliciya bagli girdi aygitlarini bulur."""
    bulunan = []
    for rc in sorted(glob.glob("/sys/class/rc/rc*")):
        for inp in sorted(glob.glob(os.path.join(rc, "input*"))):
            for ev in sorted(glob.glob(os.path.join(inp, "event*"))):
                bulunan.append("/dev/input/" + os.path.basename(ev))
    return bulunan or sorted(glob.glob("/dev/input/event*"))


class Dinleyici(object):
    """Girdi aygitindan ham scancode okur."""

    def __init__(self, aygit):
        self.aygit = aygit
        self.fd = os.open(aygit, os.O_RDONLY | os.O_NONBLOCK)
        self.tampon = b""
        self.son_kod = None
        self.son_zaman = 0.0

    def kapat(self):
        try:
            os.close(self.fd)
        except OSError:
            pass

    def bosalt(self):
        """Bekleyen olaylari atar (onceki tusun artiklari gelmesin)."""
        try:
            while True:
                if not select.select([self.fd], [], [], 0)[0]:
                    break
                if not os.read(self.fd, OLAY_BOYUT * 64):
                    break
        except OSError:
            pass
        self.tampon = b""
        self.son_kod = None

    def bekle(self, zaman_asimi):
        """Tek bir scancode bekler. -> scancode ya da None"""
        bitis = time.time() + zaman_asimi
        while time.time() < bitis:
            if not select.select([self.fd], [], [], 0.2)[0]:
                continue
            try:
                d = os.read(self.fd, OLAY_BOYUT * 64)
            except (BlockingIOError, OSError):
                continue
            if not d:
                continue
            self.tampon += d

            while len(self.tampon) >= OLAY_BOYUT:
                paket = self.tampon[:OLAY_BOYUT]
                self.tampon = self.tampon[OLAY_BOYUT:]
                _sn, _us, tur, kod, deger = struct.unpack(OLAY_BICIM, paket)

                if tur != EV_MSC or kod != MSC_SCAN:
                    continue

                sc = deger & 0xFFFFFFFF
                simdi = time.time()
                # basili tutmadan gelen tekrarlari ele
                if sc == self.son_kod and simdi - self.son_zaman < TEKRAR_ESIGI:
                    self.son_zaman = simdi
                    continue
                self.son_kod, self.son_zaman = sc, simdi
                return sc
        return None


def girdi_var_mi():
    """Klavyeden ENTER/q gelmis mi (engellemeden bakar)."""
    try:
        if select.select([sys.stdin], [], [], 0)[0]:
            return sys.stdin.readline().strip().lower()
    except Exception:
        pass
    return None


# ----------------------------------------------------------------------
# Kayit kipleri
# ----------------------------------------------------------------------

def rehberli_kayit(dinleyici, tus_asimi=25.0):
    """Sirayla tus sorar, basilan kodu kaydeder."""
    print()
    print("  Kumanda ogretme")
    print("  " + "-" * 56)
    print("  Her tus icin kumandada ilgili tusa BIR KEZ bas.")
    print("  Atlamak icin ENTER, bitirmek icin  q + ENTER")
    print("  " + "-" * 56)
    print()

    kayitlar = []          # (scancode, keycode_adi, aciklama)
    kullanilan = {}        # scancode -> keycode adi (ayni kodu iki kez almamak icin)

    for keycode_adi, aciklama in TUS_LISTESI:
        sys.stdout.write("  %-22s : " % aciklama)
        sys.stdout.flush()
        dinleyici.bosalt()

        bitis = time.time() + tus_asimi
        sonuc = None
        while time.time() < bitis:
            komut = girdi_var_mi()
            if komut is not None:
                sonuc = "bitir" if komut == "q" else "atla"
                break
            sc = dinleyici.bekle(0.4)
            if sc is not None:
                sonuc = sc
                break

        if sonuc == "bitir":
            print("kayit bitirildi")
            break
        if sonuc == "atla" or sonuc is None:
            print("atlandi")
            continue

        if sonuc in kullanilan:
            print("0x%08X  (zaten %s icin kayitli, atlandi)" % (sonuc, kullanilan[sonuc]))
            continue

        kullanilan[sonuc] = keycode_adi
        kayitlar.append((sonuc, keycode_adi, aciklama))
        print("0x%08X" % sonuc)
        time.sleep(0.35)       # tusu birakmasi icin kisa bekleme

    return kayitlar


def serbest_kayit(dinleyici, sure=120.0):
    """Butun tuslari sirayla dinler, adlandirma yapmaz.

    Kumandada hangi tusun hangi kodu urettigini gormek icin kullanisli;
    cikan kodlari sonradan elle adlandirabilirsin.
    """
    print()
    print("  Serbest dinleme  (%d saniye)" % sure)
    print("  " + "-" * 56)
    print("  Tuslara tek tek bas, arada yarim saniye birak.")
    print()

    kayitlar = []
    gorulen = set()
    bitis = time.time() + sure
    while time.time() < bitis:
        if girdi_var_mi() == "q":
            break
        sc = dinleyici.bekle(0.5)
        if sc is None or sc in gorulen:
            continue
        gorulen.add(sc)
        ad = "KEY_TUS%d" % len(gorulen)
        kayitlar.append((sc, ad, "adlandirilmadi"))
        print("  %2d. 0x%08X   komut 0x%02X" % (len(gorulen), sc, (sc >> 8) & 0xFF))
        sys.stdout.flush()
    return kayitlar


# ----------------------------------------------------------------------
# Cikti
# ----------------------------------------------------------------------

def adres_dagilimi(kayitlar):
    """NEC kodlarinin ust 16 biti cihaz adresidir; dagilimi sayar.

    Kumandanin bazi tuslari (ust bloktaki TV kontrol tuslari gibi) farkli
    bir adres kullanabilir.  Bunlari ayirt etmek isteyebilirsin.
    """
    sayac = {}
    for sc, _ad, _acik in kayitlar:
        adres = (sc >> 16) & 0xFFFF
        sayac[adres] = sayac.get(adres, 0) + 1
    return sayac


def keymap_yaz(yol, kayitlar, aygit):
    zaman = time.strftime("%Y-%m-%d %H:%M")
    adresler = adres_dagilimi(kayitlar)
    ana_adres = max(adresler, key=adresler.get) if adresler else 0

    satirlar = [
        "# kumanda_kaydet.py ile uretildi - %s" % zaman,
        "# aygit: %s" % aygit,
        "# cihaz adresi: 0x%04X  (%d tus)" % (ana_adres, adresler.get(ana_adres, 0)),
    ]
    if len(adresler) > 1:
        satirlar.append("#")
        satirlar.append("# UYARI: birden fazla cihaz adresi goruldu:")
        for adres, n in sorted(adresler.items(), key=lambda x: -x[1]):
            satirlar.append("#   0x%04X - %d tus%s" % (
                adres, n, "  <- ana" if adres == ana_adres else ""))
        satirlar.append("# Farkli adresli tuslar cogunlukla TV kontrol tuslaridir;")
        satirlar.append("# aliciya ulasmazlar, satirlarini silebilirsin.")
    satirlar += ["#", "# scancode   keycode", ""]

    for sc, ad, acik in kayitlar:
        yorum = ("  # %s" % acik) if acik and acik != "adlandirilmadi" else ""
        satirlar.append("0x%08x %s%s" % (sc, ad, yorum))

    with open(yol, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(satirlar) + "\n")


def main():
    argv = sys.argv[1:]

    cikti = "kumanda.keymap"
    if "-o" in argv:
        i = argv.index("-o")
        if i + 1 < len(argv):
            cikti = argv[i + 1]

    aygit = None
    if "--aygit" in argv:
        i = argv.index("--aygit")
        if i + 1 < len(argv):
            aygit = argv[i + 1]

    if aygit is None:
        adaylar = rc_aygitlari()
        if not adaylar:
            print("girdi aygiti bulunamadi (/dev/input/event*)")
            return 1
        aygit = adaylar[0]
        if len(adaylar) > 1:
            print("  birden fazla aygit var, kullanilan: %s" % aygit)
            print("  digerleri: %s" % ", ".join(adaylar[1:]))
            print("  farkli birini denemek icin: --aygit /dev/input/eventN")

    if not os.path.exists(aygit):
        print("aygit yok: %s" % aygit)
        return 1

    try:
        dinleyici = Dinleyici(aygit)
    except OSError as e:
        print("aygit acilamadi: %s" % e)
        return 1

    # Enigma2 aygiti kilitlemis olabilir; kullaniciyi bilgilendir
    print()
    print("  aygit: %s" % aygit)
    print("  (hicbir tus yakalanmiyorsa once 'init 4' ile Enigma2'yi durdur)")

    try:
        if "--hepsi" in argv:
            kayitlar = serbest_kayit(dinleyici)
        else:
            kayitlar = rehberli_kayit(dinleyici)
    except KeyboardInterrupt:
        print()
        print("  iptal edildi")
        kayitlar = []
    finally:
        dinleyici.kapat()

    if not kayitlar:
        print()
        print("  hicbir tus kaydedilmedi, dosya yazilmadi")
        return 1

    keymap_yaz(cikti, kayitlar, aygit)

    print()
    print("  %d tus kaydedildi -> %s" % (len(kayitlar), cikti))
    adresler = adres_dagilimi(kayitlar)
    for adres, n in sorted(adresler.items(), key=lambda x: -x[1]):
        print("    cihaz adresi 0x%04X : %d tus" % (adres, n))
    print()
    print("  Simdi yuklemek icin:")
    print("      python3 kumanda_yukle.py %s" % cikti)
    print("  Kalici hale getirmek icin:")
    print("      python3 kur.py --keymap %s" % cikti)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
