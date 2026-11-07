# -*- coding: utf-8 -*-
"""
Kumanda Tanitma Sihirbazi - Enigma2 eklentisi.

Yeni (farkli marka) bir kumandayi TV ekranindan adim adim tanitir:
ekranda "su tusa bas" yazar, kumandadan gelen ham NEC kodunu yakalar,
sonunda kernel tus haritasina yazar ve kalici yapar.

NASIL CALISIR
-------------
Enigma2 kizilotesi girdi aygitini EVIOCGRAB ile tekeline alir; baska bir
surec ham olaylari goremez.  Sihirbaz Enigma2'nin icinde calistigi icin
eRCInput.lock() ile kilidi birakir, /dev/input/eventN'den MSC_SCAN
olaylarini kendisi okur.  Kernel'in tanimadigi tuslar da MSC_SCAN uretir.
Bitince EVIOCSKEYCODE ile scancode -> keycode eslemesini yazar ve
eRCInput.unlock() ile kilidi geri verir; yeni kumanda hemen calisir.

Harita /etc/kumanda_sihirbazi.keymap dosyasina yazilir ve her Enigma2
acilisinda (sessionstart) yeniden uygulanir.

BASLATMA (kumanda yokken)
-------------------------
    /tmp/kumanda_sihirbazi_baslat dosyasi olusturulunca sihirbaz acilir.
    PC'den:  curl -s -T /dev/null ftp://root:<parola>@<ip>/tmp/kumanda_sihirbazi_baslat
Kumanda calisiyorsa: Eklentiler menusu -> Kumanda Tanitma Sihirbazi.

KULLANIM (ekranda)
------------------
    1. adim OK, 2. adim EXIT ogrenilir.
    Kumandada olmayan tus  -> OK  (atlanir)
    Yanlis kaydettim       -> EXIT (onceki tusa doner)
    Erken bitir            -> OK'a 3 sn basili tut
"""

import os
import glob
import time
import fcntl
import struct

from enigma import eTimer, eRCInput, gRGB
from Screens.Screen import Screen
from Components.Label import Label
from Components.ProgressBar import ProgressBar
from Components.ActionMap import ActionMap
from Plugins.Plugin import PluginDescriptor

KEYMAP_YOL = "/etc/kumanda_sihirbazi.keymap"
BAYRAK_YOL = "/tmp/kumanda_sihirbazi_baslat"
LOG_YOL = "/tmp/kumanda_sihirbazi.log"

# struct input_event 32-bit ARM'de 16 bayt: timeval(2 x long) + u16 + u16 + s32
OLAY_BICIM = "<llHHi"
OLAY_BOYUT = struct.calcsize(OLAY_BICIM)
EV_MSC = 0x04
MSC_SCAN = 0x04

TUTMA_ESIGI = 0.35       # bu sureden kisa aralikla gelen ayni kod = basili tutma
SESSIZ_SURE = 0.6        # kayittan sonra bu sure butun olaylar yok sayilir
BITIR_TUTMA = 3.0        # OK bu kadar basili tutulursa erken bitir
BOSTA_ASIMI = 600        # hic tusa basilmazsa (sn) kaydedip kapanir
SINYAL_UYARI = 25        # ilk adimda bu kadar sinyal gelmezse ipucu goster


def _IOW(tur, nr, boyut):
    return (1 << 30) | (boyut << 16) | (ord(tur) << 8) | nr


EVIOCSKEYCODE = _IOW("E", 0x04, 8)

KEYCODES = {
    "KEY_OK": 352, "KEY_EXIT": 174, "KEY_POWER": 116, "KEY_MENU": 139,
    "KEY_UP": 103, "KEY_DOWN": 108, "KEY_LEFT": 105, "KEY_RIGHT": 106,
    "KEY_INFO": 358, "KEY_EPG": 365, "KEY_HELP": 138,
    "KEY_VOLUMEUP": 115, "KEY_VOLUMEDOWN": 114, "KEY_MUTE": 113,
    "KEY_CHANNELUP": 402, "KEY_CHANNELDOWN": 403,
    "KEY_1": 2, "KEY_2": 3, "KEY_3": 4, "KEY_4": 5, "KEY_5": 6,
    "KEY_6": 7, "KEY_7": 8, "KEY_8": 9, "KEY_9": 10, "KEY_0": 11,
    "KEY_RED": 398, "KEY_GREEN": 399, "KEY_YELLOW": 400, "KEY_BLUE": 401,
    "KEY_TEXT": 388, "KEY_SUBTITLE": 370, "KEY_AUDIO": 392,
    "KEY_FAVORITES": 364, "KEY_TV": 377, "KEY_RADIO": 385,
    "KEY_PREVIOUS": 412, "KEY_NEXT": 407,
    "KEY_PLAYPAUSE": 164, "KEY_STOP": 128, "KEY_RECORD": 167,
    "KEY_REWIND": 168, "KEY_FASTFORWARD": 208, "KEY_PVR": 366,
    "KEY_SLEEP": 142, "KEY_VMODE": 375,
}

# (keycode adi, ekranda gorunen ad, ek aciklama)
# Ilk iki tus sabittir: OK = atla, EXIT = geri.
TUSLAR = [
    ("KEY_OK", "OK", "Ortadaki onay tuşu"),
    ("KEY_EXIT", "EXIT / GERİ", "Çıkış ya da geri tuşu"),
    ("KEY_POWER", "GÜÇ", "Aç / kapat tuşu"),
    ("KEY_UP", "YUKARI  ▲", "Yön tuşu"),
    ("KEY_DOWN", "AŞAĞI  ▼", "Yön tuşu"),
    ("KEY_LEFT", "SOL  ◀", "Yön tuşu"),
    ("KEY_RIGHT", "SAĞ  ▶", "Yön tuşu"),
    ("KEY_MENU", "MENU", "Ana menü tuşu"),
    ("KEY_INFO", "INFO / BİLGİ", "Kanal bilgisi tuşu"),
    ("KEY_EPG", "EPG", "Yayın akışı tuşu"),
    ("KEY_VOLUMEUP", "SES +", ""),
    ("KEY_VOLUMEDOWN", "SES −", ""),
    ("KEY_MUTE", "SESSİZ", "Sesi kapatma tuşu"),
    ("KEY_CHANNELUP", "KANAL +", "Program / sayfa yukarı"),
    ("KEY_CHANNELDOWN", "KANAL −", "Program / sayfa aşağı"),
    ("KEY_1", "1", "Rakam tuşu"),
    ("KEY_2", "2", "Rakam tuşu"),
    ("KEY_3", "3", "Rakam tuşu"),
    ("KEY_4", "4", "Rakam tuşu"),
    ("KEY_5", "5", "Rakam tuşu"),
    ("KEY_6", "6", "Rakam tuşu"),
    ("KEY_7", "7", "Rakam tuşu"),
    ("KEY_8", "8", "Rakam tuşu"),
    ("KEY_9", "9", "Rakam tuşu"),
    ("KEY_0", "0", "Rakam tuşu"),
    ("KEY_RED", "KIRMIZI", "Renkli tuş"),
    ("KEY_GREEN", "YEŞİL", "Renkli tuş"),
    ("KEY_YELLOW", "SARI", "Renkli tuş"),
    ("KEY_BLUE", "MAVİ", "Renkli tuş"),
    ("KEY_PREVIOUS", "ÖNCEKİ KANAL", "Recall / Back / ↺ tuşu"),
    ("KEY_TEXT", "TELETEXT", "TXT tuşu"),
    ("KEY_SUBTITLE", "ALTYAZI", "SUB tuşu"),
    ("KEY_AUDIO", "SES SEÇİMİ", "Audio / dil tuşu"),
    ("KEY_FAVORITES", "FAVORİ", "FAV tuşu"),
    ("KEY_TV", "TV", "TV / kanal listesi"),
    ("KEY_RADIO", "RADYO", ""),
    ("KEY_HELP", "HELP / YARDIM", ""),
    ("KEY_PLAYPAUSE", "OYNAT / DURAKLAT", "▶ ❚❚"),
    ("KEY_STOP", "DURDUR", "■"),
    ("KEY_RECORD", "KAYIT", "● REC"),
    ("KEY_REWIND", "GERİ SAR", "◀◀"),
    ("KEY_FASTFORWARD", "İLERİ SAR", "▶▶"),
    ("KEY_PVR", "KAYITLAR", "PVR / Media / Kayıt listesi"),
    ("KEY_SLEEP", "UYKU", "Sleep tuşu"),
    ("KEY_VMODE", "ÇÖZÜNÜRLÜK", "V.Format / Res tuşu"),
]


def log(m):
    try:
        with open(LOG_YOL, "a") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), m))
    except Exception:
        pass


def rc_aygitlari():
    bulunan = []
    for rc in sorted(glob.glob("/sys/class/rc/rc*")):
        for inp in sorted(glob.glob(os.path.join(rc, "input*"))):
            for ev in sorted(glob.glob(os.path.join(inp, "event*"))):
                bulunan.append("/dev/input/" + os.path.basename(ev))
    return bulunan or sorted(glob.glob("/dev/input/event*"))


def keymap_oku(yol):
    girdiler = []
    try:
        with open(yol, "r", encoding="utf-8") as f:
            for satir in f:
                satir = satir.split("#")[0].strip()
                if not satir:
                    continue
                p = satir.split()
                if len(p) < 2:
                    continue
                try:
                    sc = int(p[0], 16)
                    kc = KEYCODES[p[1]] if p[1] in KEYCODES else int(p[1], 0)
                except (ValueError, KeyError):
                    continue
                girdiler.append((sc, kc))
    except (IOError, OSError):
        pass
    return girdiler


def haritayi_uygula(girdiler):
    """scancode -> keycode eslemesini rc aygitlarina yazar. -> yazilan sayisi"""
    toplam = 0
    for aygit in rc_aygitlari():
        try:
            fd = os.open(aygit, os.O_RDWR)
        except OSError as e:
            log("acilamadi %s: %s" % (aygit, e))
            continue
        try:
            for sc, kc in girdiler:
                try:
                    fcntl.ioctl(fd, EVIOCSKEYCODE, struct.pack("<II", sc, kc))
                    toplam += 1
                except OSError:
                    pass
        finally:
            os.close(fd)
    return toplam


class KumandaSihirbazi(Screen):
    skin = """
    <screen name="KumandaSihirbazi" position="0,0" size="1920,1080" flags="wfNoBorder" backgroundColor="#00101418">
        <eLabel zPosition="0" position="160,90" size="1600,900" backgroundColor="#001b222b" />
        <eLabel zPosition="1" position="160,90" size="1600,6" backgroundColor="#002f81f7" />
        <widget zPosition="2" name="baslik" position="220,130" size="1100,60" font="Regular;44" foregroundColor="#00ffffff" backgroundColor="#001b222b" />
        <widget zPosition="2" name="adim" position="1320,138" size="380,50" font="Regular;34" halign="right" foregroundColor="#008b98a8" backgroundColor="#001b222b" />
        <widget zPosition="2" name="ilerleme" position="220,210" size="1480,12" foregroundColor="#002f81f7" backgroundColor="#00303a46" />
        <widget zPosition="2" name="ust" position="220,280" size="1480,50" font="Regular;36" halign="center" foregroundColor="#00c9d3de" backgroundColor="#001b222b" />
        <widget zPosition="2" name="tus" position="220,340" size="1480,170" font="Regular;130" halign="center" valign="center" foregroundColor="#00ffd24a" backgroundColor="#001b222b" />
        <widget zPosition="2" name="aciklama" position="220,515" size="1480,50" font="Regular;34" halign="center" foregroundColor="#008b98a8" backgroundColor="#001b222b" />
        <widget zPosition="2" name="durum" position="220,600" size="1480,60" font="Regular;38" halign="center" foregroundColor="#004cd07d" backgroundColor="#001b222b" />
        <eLabel zPosition="1" position="220,700" size="1480,2" backgroundColor="#00303a46" />
        <widget zPosition="2" name="ipucu" position="220,725" size="1480,170" font="Regular;32" foregroundColor="#00c9d3de" backgroundColor="#001b222b" />
        <widget zPosition="2" name="alt" position="220,910" size="1480,50" font="Regular;28" foregroundColor="#006b7785" backgroundColor="#001b222b" />
    </screen>"""

    def __init__(self, session):
        Screen.__init__(self, session)
        self.setTitle("Kumanda Tanıtma Sihirbazı")
        self["baslik"] = Label("Kumanda Tanıtma Sihirbazı")
        self["adim"] = Label("")
        self["ilerleme"] = ProgressBar()
        self["ust"] = Label("")
        self["tus"] = Label("")
        self["aciklama"] = Label("")
        self["durum"] = Label("")
        self["ipucu"] = Label("")
        self["alt"] = Label("")
        self["actions"] = ActionMap(["OkCancelActions"], {
            "ok": self.kapatIstegi, "cancel": self.kapatIstegi}, -1)

        self.adim = 0
        self.kayit = {}            # adim no -> scancode (None = atlandi)
        self.kod_adim = {}         # scancode -> adim no
        self.fd = None
        self.tampon = b""
        self.son_kod = None
        self.son_zaman = 0.0
        self.sessiz_bitis = 0.0
        self.ok_basili = False
        self.ok_baslangic = 0.0
        self.son_basim = time.time()
        self.baslangic = time.time()
        self.sinyal_goruldu = False
        self.bitti = False
        self.kilitli = False

        self.okuyucu = eTimer()
        self.okuyucu.callback.append(self.oku)
        self.saat = eTimer()
        self.saat.callback.append(self.saniyelik)
        self.kapatici = eTimer()
        self.kapatici.callback.append(self.close)

        self.onLayoutFinish.append(self.basla)
        self.onClose.append(self.temizle)

    # ------------------------------------------------------------------
    def basla(self):
        aygitlar = rc_aygitlari()
        if not aygitlar:
            self.hataGoster("Kızılötesi alıcı bulunamadı (/dev/input/event*).")
            return
        try:
            eRCInput.getInstance().lock()
            self.kilitli = True
            self.fd = os.open(aygitlar[0], os.O_RDONLY | os.O_NONBLOCK)
        except Exception as e:
            log("baslatma hatasi: %s" % e)
            self.hataGoster("Alıcı açılamadı: %s" % e)
            return
        log("sihirbaz basladi, aygit %s" % aygitlar[0])
        self.bosalt()
        self.okuyucu.start(40, False)
        self.saat.start(1000, False)
        self.adimGoster()

    def temizle(self):
        self.okuyucu.stop()
        self.saat.stop()
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None
        if self.kilitli:
            try:
                eRCInput.getInstance().unlock()
            except Exception:
                pass
            self.kilitli = False
        log("sihirbaz kapandi")

    def kapatIstegi(self):
        # Kayit surerken eski haritadaki tuslar yanlislikla kapatmasin.
        if self.bitti:
            self.close()

    def hataGoster(self, metin):
        self.bitti = True
        self["tus"].setText("HATA")
        self["durum"].setText(metin)
        self["ipucu"].setText("Sihirbaz 20 saniye içinde kapanacak.")
        self.kapatici.start(20000, True)

    # ------------------------------------------------------------------
    def bosalt(self):
        try:
            while os.read(self.fd, OLAY_BOYUT * 64):
                pass
        except OSError:
            pass
        self.tampon = b""

    def oku(self):
        if self.fd is None or self.bitti:
            return
        try:
            veri = os.read(self.fd, OLAY_BOYUT * 64)
        except OSError:
            veri = b""
        simdi = time.time()
        if veri:
            self.tampon += veri
            while len(self.tampon) >= OLAY_BOYUT:
                paket = self.tampon[:OLAY_BOYUT]
                self.tampon = self.tampon[OLAY_BOYUT:]
                _s, _u, tur, kod, deger = struct.unpack(OLAY_BICIM, paket)
                if tur == EV_MSC and kod == MSC_SCAN:
                    self.kodGeldi(deger & 0xFFFFFFFF, simdi)

        # OK birakildi mi / uzun basildi mi
        if self.ok_basili:
            if simdi - self.ok_baslangic >= BITIR_TUTMA:
                self.ok_basili = False
                self.son_kod = None
                self.bitir("OK basılı tutuldu, kayıt erken bitirildi.")
            elif simdi - self.son_zaman > TUTMA_ESIGI:
                self.ok_basili = False
                self.atla()

    def kodGeldi(self, sc, simdi):
        if not self.sinyal_goruldu:
            self.sinyal_goruldu = True
            log("ilk sinyal 0x%08x" % sc)
        # Basili tutma tekrarlari
        if sc == self.son_kod and simdi - self.son_zaman < TUTMA_ESIGI:
            self.son_zaman = simdi
            return
        self.son_kod, self.son_zaman = sc, simdi
        if simdi < self.sessiz_bitis:
            return
        self.son_basim = simdi
        log("adim %d kod 0x%08x" % (self.adim, sc))

        ok_kodu = self.kayit.get(0)
        exit_kodu = self.kayit.get(1)

        if self.adim >= 2 and sc == ok_kodu:
            # Atla ya da (uzun basilirsa) bitir; karar birakinca verilir.
            self.ok_basili = True
            self.ok_baslangic = simdi
            return
        if self.adim >= 2 and exit_kodu is not None and sc == exit_kodu:
            self.geri()
            return
        if self.adim == 1 and sc == ok_kodu:
            # EXIT adiminda OK: EXIT yok sayilir, geri ozelligi kapanir.
            self.kayit[1] = None
            self.ilerle("EXIT atlandı (geri alma kapalı).", uyari=True)
            return
        if sc in self.kod_adim:
            eski = TUSLAR[self.kod_adim[sc]][1]
            self.durumYaz("Bu tuş zaten %s olarak kaydedildi. Başka tuşa bas." % eski, uyari=True)
            return

        adi = TUSLAR[self.adim][1]
        self.kayit[self.adim] = sc
        self.kod_adim[sc] = self.adim
        self.ilerle("✓ %s kaydedildi  (0x%08X)" % (adi, sc))

    def ilerle(self, mesaj, uyari=False):
        self.sessiz_bitis = time.time() + SESSIZ_SURE
        self.adim += 1
        if self.adim >= len(TUSLAR):
            self.bitir("Bütün tuşlar soruldu.")
            return
        self.adimGoster()
        self.durumYaz(mesaj, uyari)

    def atla(self):
        if self.adim < 2 or self.bitti:
            return
        adi = TUSLAR[self.adim][1]
        self.kayit[self.adim] = None
        self.ilerle("%s atlandı." % adi, uyari=True)

    def geri(self):
        if self.adim <= 2:
            self.durumYaz("OK ve EXIT değiştirilemez. Bu tuşa bas ya da OK ile atla.", uyari=True)
            return
        self.sessiz_bitis = time.time() + SESSIZ_SURE
        self.adim -= 1
        eski = self.kayit.pop(self.adim, None)
        if eski is not None:
            self.kod_adim.pop(eski, None)
        self.adimGoster()
        self.durumYaz("Geri dönüldü: %s tuşunu yeniden bas." % TUSLAR[self.adim][1], uyari=True)

    # ------------------------------------------------------------------
    def adimGoster(self):
        kod, adi, acik = TUSLAR[self.adim]
        n = len(TUSLAR)
        self["adim"].setText("Adım %d / %d" % (self.adim + 1, n))
        self["ilerleme"].setValue(int(100 * self.adim / n))
        self["ust"].setText("Yeni kumandada şu tuşa bir kez bas:")
        self["tus"].setText(adi)
        self["aciklama"].setText(acik)
        if self.adim == 0:
            self["ipucu"].setText(
                "Önce OK, sonra EXIT öğrenilecek. Sonraki adımlarda:\n"
                "•  Kumandanda o tuş yoksa  →  OK'a bas, atlanır\n"
                "•  Yanlış tuşa bastıysan  →  EXIT'e bas, bir önceki tuşa döner")
        elif self.adim == 1:
            self["ipucu"].setText(
                "EXIT, yanlış kaydı geri almak için kullanılacak.\n"
                "Kumandanda EXIT/BACK yoksa OK'a bas.")
        else:
            self["ipucu"].setText(
                "•  Bu tuş kumandanda yoksa  →  OK  (atla)\n"
                "•  Önceki tuşu düzelt  →  EXIT\n"
                "•  Bitirmek için  →  OK'a 3 saniye basılı tut")

    def durumYaz(self, metin, uyari=False):
        self["durum"].instance.setForegroundColor(
            gRGB(0xffb84a if uyari else 0x4cd07d))
        self["durum"].setText(metin)

    def saniyelik(self):
        if self.bitti:
            return
        simdi = time.time()
        kalan = int(BOSTA_ASIMI - (simdi - self.son_basim))
        kayitli = len([v for v in self.kayit.values() if v is not None])
        self["alt"].setText("Kaydedilen tuş: %d     ·     %d:%02d boyunca tuşa basılmazsa kaydedip kapanır"
                            % (kayitli, max(kalan, 0) // 60, max(kalan, 0) % 60))
        if not self.sinyal_goruldu and simdi - self.baslangic > SINYAL_UYARI:
            self.durumYaz("Sinyal yok: pilleri kontrol et, kumandayı kutuya doğrult.", uyari=True)
            if self.adim == 0:
                self["aciklama"].setText("Not: alıcı yalnız NEC kodlu kumandaları tanır")
        if kalan <= 0:
            self.bitir("Uzun süre tuşa basılmadı.")

    # ------------------------------------------------------------------
    def bitir(self, neden):
        if self.bitti:
            return
        self.bitti = True
        self.okuyucu.stop()
        self.saat.stop()

        kayitlar = [(self.kayit[i], TUSLAR[i][0], TUSLAR[i][1])
                    for i in sorted(self.kayit) if self.kayit[i] is not None]
        if self.fd is not None:
            try:
                os.close(self.fd)
            except OSError:
                pass
            self.fd = None

        self["ilerleme"].setValue(100)
        self["adim"].setText("")
        self["ust"].setText(neden)
        self["aciklama"].setText("")

        if not kayitlar:
            self["tus"].setText("Kayıt yok")
            self.durumYaz("Hiç tuş kaydedilmedi; eski harita değişmedi.", uyari=True)
            self["ipucu"].setText("Sihirbazı yeniden başlatmak için PC'den bayrak dosyası gönder.")
            self["alt"].setText("")
            self.kilidiAc()
            self.kapatici.start(30000, True)
            return

        try:
            self.keymapYaz(kayitlar)
            yazilan = haritayi_uygula([(sc, KEYCODES[k]) for sc, k, _a in kayitlar])
        except Exception as e:
            log("kaydetme hatasi: %s" % e)
            self.kilidiAc()
            self.hataGoster("Kaydedilemedi: %s" % e)
            return
        log("bitti: %d tus, %d yazildi" % (len(kayitlar), yazilan))
        self.kilidiAc()

        self["tus"].setText("TAMAM  ✓")
        self.durumYaz("%d tuş tanıtıldı ve kalıcı olarak kaydedildi." % len(kayitlar))
        self["ipucu"].setText(
            "Yeni kumandan şimdi çalışıyor. Denemek için OK ya da EXIT'e bas, ekran kapanır.\n"
            "Harita: %s  (her açılışta otomatik yüklenir)" % KEYMAP_YOL)
        self["alt"].setText("Bu ekran 60 saniye sonra kendiliğinden kapanır.")
        self.kapatici.start(60000, True)

    def kilidiAc(self):
        if self.kilitli:
            try:
                eRCInput.getInstance().unlock()
            except Exception:
                pass
            self.kilitli = False

    def keymapYaz(self, kayitlar):
        if os.path.exists(KEYMAP_YOL):
            try:
                os.rename(KEYMAP_YOL, KEYMAP_YOL + ".yedek")
            except OSError:
                pass
        adresler = {}
        for sc, _k, _a in kayitlar:
            ad = (sc >> 16) & 0xFFFF
            adresler[ad] = adresler.get(ad, 0) + 1
        satirlar = ["# Kumanda Tanitma Sihirbazi - %s" % time.strftime("%Y-%m-%d %H:%M"),
                    "# cihaz adresleri: " + ", ".join("0x%04X (%d tus)" % (a, n)
                                                       for a, n in sorted(adresler.items(), key=lambda x: -x[1])),
                    "#", "# scancode   keycode", ""]
        for sc, k, a in kayitlar:
            satirlar.append("0x%08x %-16s # %s" % (sc, k, a))
        with open(KEYMAP_YOL, "w", encoding="utf-8") as f:
            f.write("\n".join(satirlar) + "\n")
            f.flush()
            os.fsync(f.fileno())


# ----------------------------------------------------------------------
# Acilista harita yukleme ve bayrak dosyasi ile baslatma
# ----------------------------------------------------------------------

_oturum = None
_bayrak_zamanlayici = None
_acik = [False]


def _bayrak_kontrol():
    if _oturum is None or _acik[0] or not os.path.exists(BAYRAK_YOL):
        return
    try:
        os.unlink(BAYRAK_YOL)
    except OSError:
        pass
    sihirbaziAc(_oturum)


def sihirbaziAc(session, **kwargs):
    if _acik[0]:
        return

    def kapandi(*a):
        _acik[0] = False

    _acik[0] = True
    session.openWithCallback(kapandi, KumandaSihirbazi)


def oturumBasladi(reason, session=None, **kwargs):
    global _oturum, _bayrak_zamanlayici
    if reason != 0 or session is None:
        return
    _oturum = session
    girdiler = keymap_oku(KEYMAP_YOL)
    if girdiler:
        log("acilis: %d tus uygulandi" % haritayi_uygula(girdiler))
    _bayrak_zamanlayici = eTimer()
    _bayrak_zamanlayici.callback.append(_bayrak_kontrol)
    _bayrak_zamanlayici.start(2000, False)


def Plugins(**kwargs):
    return [
        PluginDescriptor(where=PluginDescriptor.WHERE_SESSIONSTART, fnc=oturumBasladi),
        PluginDescriptor(name="Kumanda Tanıtma Sihirbazı",
                         description="Yeni kumandayı ekrandan adım adım tanıt",
                         where=[PluginDescriptor.WHERE_PLUGINMENU, PluginDescriptor.WHERE_EXTENSIONSMENU],
                         fnc=sihirbaziAc),
    ]
