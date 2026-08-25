# Enigma2 Kumanda Yükleyici

Enigma2 alıcılarda **kumanda tuşlarının hiçbiri çalışmıyorsa** bu araçlar sorunu çözer. Kernel'e dokunmadan, imaj değiştirmeden.

Next Innova 4K + OpenATV üzerinde geliştirildi ve doğrulandı, ancak yöntem kizilötesi alıcısı `rc-core` sürücüsü kullanan bütün Enigma2 cihazlarında geçerlidir.

---

## Sorun

Enigma2 imajları (OpenATV, OpenPLi, OpenViX…) belirli bir marka/model için derlenir. Kernel'in kizilötesi sürücüsü yalnızca o modelin kumandasının kodlarını tanır.

Cihazına başka bir imaj yüklediğinde — ya da kutudan çıkan kumanda imajın beklediğinden farklı bir **NEC cihaz adresi** kullanıyorsa — alıcı sinyali alır ama hangi tuşa karşılık geldiğini bilemez. Sonuç: kumanda tamamen ölü, hiçbir tuş çalışmıyor.

Next Innova 4K'da durum tam olarak buydu: OpenATV imajı Octagon SX88V2 için derlenmişti; Octagon kumandası farklı bir adres kullanıyor. Next kumandası ise `0x2962` adresini gönderiyor ve kernel bunu tanımıyordu.

## Çözüm

Kernel'in scancode → keycode tablosuna doğru eşlemeyi çalışma anında yazmak. Bu, `EVIOCSKEYCODE` ioctl'i ile yapılır:

```c
struct input_keymap_entry_v1 {
    __u32 scancode;   /* kumandadan gelen ham kod, ör. 0x296247b8 */
    __u32 keycode;    /* Linux tuş kodu, ör. KEY_OK = 352        */
};
```

Yani kernel'e "bu kodu görürsen OK tuşu say" demiş oluyoruz. `ir-keytable` aracı çoğu imajda bulunmadığı için ioctl doğrudan çağrılıyor — ek paket gerekmez, sadece Python 3 standart kütüphanesi.

Yazılan tablo bellekte tutulur ve cihaz kapanınca kaybolur; bu yüzden her açılışta yeniden yazılması gerekir. `kur.py` bunu bir init script ile hallediyor.

---

## Dosyalar

| Dosya | Nerede çalışır | Ne yapar |
|---|---|---|
| `kumanda_kaydet.py` | alıcıda | Tuşlara basarsın, keymap dosyası üretir |
| `kumanda_yukle.py` | alıcıda | Keymap'i kernel'e yazar (tek seferlik) |
| `kur.py` | alıcıda | Kalıcı kurulum: kopyalar, açılışa bağlar, uygular |
| `keymaps/*.keymap` | — | Hazır kod haritaları |

---

## Hızlı kurulum (hazır keymap varsa)

Cihazın `keymaps/` altında zaten varsa tek adım yeter.

**1.** Depoyu alıcıya kopyala — FTP ile `/tmp/kumanda/` altına at (kullanıcı `root`).

**2.** Telnet veya SSH ile bağlan:

```bash
cd /tmp/kumanda && python3 kur.py --keymap keymaps/next_innova_4k.keymap
```

Beklenen çıktı:

```
[+] keymap ve yukleyici /etc/ altina kopyalandi
[+] acilis scripti kuruldu (rcS.d + rc3.d, S99)
    /dev/input/event0      yazilan 43, reddedilen 0
[+] kumanda tanitildi ve kalici hale getirildi
```

Tuşlar hemen çalışmaya başlar. Çalışmazsa Enigma2'yi bir kez yeniden başlat:

```bash
init 4; sleep 5; init 3
```

---

## Kendi kumandanı öğretme

Elindeki kumanda `keymaps/` altındakilere uymuyorsa kendi haritanı çıkar.

**1. Enigma2'yi durdur.** Çalışırken girdi aygıtını kendine kilitleyebilir ve tuşlar scripte ulaşmaz:

```bash
init 4
```

**2. Kaydı başlat:**

```bash
cd /tmp/kumanda && python3 kumanda_kaydet.py -o benim.keymap
```

Script sırayla tuş ister:

```
  Guc                    : 0x29620AF5
  OK / Enter             : 0x296247B8
  Yon: Yukari            : 0x296245BA
  Yon: Asagi             : atlandi
```

- Kumandada ilgili tuşa **bir kez** bas → kaydeder, sonrakine geçer
- **ENTER** → o tuşu atlar
- **q + ENTER** → kaydı bitirir, o ana kadar toplananları yazar

Aynı kodu iki kez kaydetmeye çalışırsan uyarır ve atlar.

**3. Yükle ve kalıcı yap:**

```bash
python3 kur.py --keymap benim.keymap
```

**4. Enigma2'yi geri başlat:**

```bash
init 3
```

### Serbest dinleme

Hangi tuşun hangi kodu ürettiğini görmek istersen adlandırma yapmadan dinleyebilirsin:

```bash
python3 kumanda_kaydet.py --hepsi -o ham.keymap
```

Çıkan kodları sonradan elle adlandırırsın. Kernel'in hiç tanımadığı tuşlar da yakalanır — script `EV_KEY` yerine ham `MSC_SCAN` olaylarını dinlediği için.

---

## Keymap biçimi

Düz metin, satır başına bir tuş, `#` sonrası yorum:

```
# Next Innova 4K -> OpenATV
# Protokol: NEC extended, cihaz adresi 0x2962

0x296247b8 KEY_OK
0x29620af5 KEY_POWER
0x296245ba KEY_UP
0x296200ff 11              # sayısal keycode de yazılabilir
```

Tuş adı olarak `kumanda_yukle.py` içindeki `KEYCODES` tablosundaki isimlerden biri, ya da doğrudan sayısal değer kullanılır. Tablo Enigma2'nin kullandığı bütün tuşları içerir (`KEY_EPG`, `KEY_PVR`, `KEY_FAVORITES`, renkli tuşlar, oynatma tuşları…).

### Cihaz adresi

NEC protokolünde scancode'un üst 16 biti kumandanın **cihaz adresidir**:

```
0x2962 47b8
└──┬─┘ └─┬┘
adres  komut
```

Aynı kumandanın farklı blokları farklı adres kullanabilir. Next Innova'nın üst sırasındaki TV tuşları (TV Güç, SOURCE, TV VOL) `0x0E0E` adresini gönderir — bunlar televizyonu kontrol eder, alıcıya hiç ulaşmaz. Bu yüzden hazır keymap'e dahil edilmedi.

`kumanda_kaydet.py` birden fazla adres görürse üretilen dosyanın başına uyarı yazar ve dağılımı listeler.

---

## Sorun giderme

| Belirti | Sebep ve çözüm |
|---|---|
| Hiçbir tuş yakalanmıyor | Enigma2 girdi aygıtını kilitlemiş. `init 4` ile durdur, kayıttan sonra `init 3`. |
| `reddedilen` sayısı yüksek | Yanlış aygıta yazılıyor. `--aygit /dev/input/eventN` ile doğru olanı seç. |
| Yükleme başarılı ama tuşlar çalışmıyor | Enigma2 eski haritayı önbelleğe almış olabilir: `init 4; sleep 5; init 3`. |
| Açılıştan sonra tuşlar tekrar ölüyor | Açılış bağı kurulmamış: `ls -l /etc/rcS.d/S99next-kumanda` ile kontrol et. |
| Bazı tuşlar çalışıyor, bazıları çalışmıyor | Çalışmayanlar farklı cihaz adresi kullanıyor olabilir — üretilen keymap'in başındaki uyarıya bak. |

Kayıt dosyası: `/var/log/next-kumanda.log`

Kurulumu geri almak için:

```bash
python3 kur.py --kaldir
```

---

## Gereksinimler

- Enigma2 alıcı, root erişimi (telnet/SSH + FTP)
- Alıcıda Python 3 (imajların hepsinde vardır)
- `/dev/input/event*` altında kizilötesi alıcının girdi aygıtı

Harici Python paketi gerekmez.

---

## Katkı

Kendi cihazının keymap'ini çıkardıysan `keymaps/` altına ekleyip PR gönderebilirsin. Dosya adı `marka_model.keymap` biçiminde olsun, başına cihaz adresini ve imaj bilgisini yorum olarak yaz.

## Lisans

MIT
