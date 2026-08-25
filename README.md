# Enigma2 Kumanda Yükleyici · Remote Control Loader

**[Türkçe](#türkçe) · [English](#english)**

Enigma2 alıcılarda çalışmayan kumandayı tanıtır — kernel değişmez, `ir-keytable` gerekmez.
Makes a dead remote work on Enigma2 receivers — no kernel changes, no `ir-keytable` needed.

---

# Türkçe

Enigma2 alıcılarda **kumanda tuşlarının hiçbiri çalışmıyorsa** bu araçlar sorunu çözer. Kernel'e dokunmadan, imaj değiştirmeden.

Next Innova 4K + OpenATV üzerinde geliştirildi ve doğrulandı, ancak yöntem kizilötesi alıcısı `rc-core` sürücüsü kullanan bütün Enigma2 cihazlarında geçerlidir.

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

## Dosyalar

| Dosya | Nerede çalışır | Ne yapar |
|---|---|---|
| `kumanda_kaydet.py` | alıcıda | Tuşlara basarsın, keymap dosyası üretir |
| `kumanda_yukle.py` | alıcıda | Keymap'i kernel'e yazar (tek seferlik) |
| `kur.py` | alıcıda | Kalıcı kurulum: kopyalar, açılışa bağlar, uygular |
| `keymaps/*.keymap` | — | Hazır kod haritaları |

## Hızlı kurulum (hazır keymap varsa)

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

## Gereksinimler

- Enigma2 alıcı, root erişimi (telnet/SSH + FTP)
- Alıcıda Python 3 (imajların hepsinde vardır)
- `/dev/input/event*` altında kizilötesi alıcının girdi aygıtı

Harici Python paketi gerekmez.

## Katkı

Kendi cihazının keymap'ini çıkardıysan `keymaps/` altına ekleyip PR gönderebilirsin. Dosya adı `marka_model.keymap` biçiminde olsun, başına cihaz adresini ve imaj bilgisini yorum olarak yaz.

---

# English

If **none of your remote's buttons work** on an Enigma2 receiver, these tools fix it — without touching the kernel or reflashing the image.

Developed and verified on a Next Innova 4K running OpenATV, but the method applies to any Enigma2 device whose infrared receiver uses the `rc-core` driver.

## The problem

Enigma2 images (OpenATV, OpenPLi, OpenViX…) are built for a specific brand and model. The kernel's infrared driver only recognises the scancodes of that model's remote.

When you flash a different image — or when the remote that came in the box uses a different **NEC device address** than the image expects — the receiver picks up the signal but has no idea which button it maps to. The result: a completely dead remote.

That was exactly the case on the Next Innova 4K: the OpenATV image was built for the Octagon SX88V2, whose remote uses a different address. The Next remote sends address `0x2962`, which the kernel did not recognise.

## The fix

Write the correct mapping into the kernel's scancode → keycode table at runtime, using the `EVIOCSKEYCODE` ioctl:

```c
struct input_keymap_entry_v1 {
    __u32 scancode;   /* raw code from the remote, e.g. 0x296247b8 */
    __u32 keycode;    /* Linux key code, e.g. KEY_OK = 352         */
};
```

In other words, we tell the kernel "when you see this code, treat it as OK". The `ir-keytable` utility is missing from most images, so the ioctl is called directly — no extra packages, just the Python 3 standard library.

The table lives in memory and is lost when the box powers off, so it has to be rewritten on every boot. `kur.py` handles that with an init script.

## Files

| File | Runs on | What it does |
|---|---|---|
| `kumanda_kaydet.py` | receiver | You press the buttons, it produces a keymap file |
| `kumanda_yukle.py` | receiver | Writes a keymap into the kernel (one-shot) |
| `kur.py` | receiver | Permanent install: copies files, hooks into boot, applies |
| `keymaps/*.keymap` | — | Ready-made keymaps |

## Quick install (if a keymap already exists)

**1.** Copy the repository to the receiver — drop it into `/tmp/kumanda/` over FTP (user `root`).

**2.** Connect over telnet or SSH:

```bash
cd /tmp/kumanda && python3 kur.py --keymap keymaps/next_innova_4k.keymap
```

Expected output:

```
[+] keymap ve yukleyici /etc/ altina kopyalandi
[+] acilis scripti kuruldu (rcS.d + rc3.d, S99)
    /dev/input/event0      yazilan 43, reddedilen 0
[+] kumanda tanitildi ve kalici hale getirildi
```

Buttons start working right away. If they don't, restart Enigma2 once:

```bash
init 4; sleep 5; init 3
```

## Teaching your own remote

If your remote doesn't match anything under `keymaps/`, record your own.

**1. Stop Enigma2.** While running it may grab the input device, and key presses never reach the script:

```bash
init 4
```

**2. Start recording:**

```bash
cd /tmp/kumanda && python3 kumanda_kaydet.py -o mine.keymap
```

The script asks for one button at a time (prompts are in Turkish; `Guc` = Power, `Yon` = Direction):

```
  Guc                    : 0x29620AF5
  OK / Enter             : 0x296247B8
  Yon: Yukari            : 0x296245BA
  Yon: Asagi             : atlandi
```

- Press the matching button **once** → recorded, moves to the next
- **ENTER** → skip this button
- **q + ENTER** → finish and write what was collected so far

If you record the same code twice it warns you and skips it.

**3. Load it and make it permanent:**

```bash
python3 kur.py --keymap mine.keymap
```

**4. Start Enigma2 again:**

```bash
init 3
```

### Free-run capture

To see which button emits which code, without naming anything:

```bash
python3 kumanda_kaydet.py --hepsi -o raw.keymap
```

Name the codes afterwards by hand. Buttons the kernel doesn't recognise at all are captured too — the script listens to raw `MSC_SCAN` events rather than `EV_KEY`.

## Keymap format

Plain text, one button per line, `#` starts a comment:

```
# Next Innova 4K -> OpenATV
# NEC extended, device address 0x2962

0x296247b8 KEY_OK
0x29620af5 KEY_POWER
0x296245ba KEY_UP
0x296200ff 11              # a numeric keycode works too
```

Use any name from the `KEYCODES` table in `kumanda_yukle.py`, or a numeric value. The table covers every key Enigma2 uses (`KEY_EPG`, `KEY_PVR`, `KEY_FAVORITES`, colour buttons, transport keys…).

### Device address

In the NEC protocol the upper 16 bits of the scancode are the remote's **device address**:

```
0x2962 47b8
└──┬─┘ └─┬┘
address command
```

Different blocks of the same remote may use different addresses. The top row on the Next Innova (TV Power, SOURCE, TV VOL) sends address `0x0E0E` — those keys drive the television and never reach the receiver, which is why they're excluded from the bundled keymap.

If `kumanda_kaydet.py` sees more than one address, it writes a warning and the distribution at the top of the generated file.

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| No key presses captured | Enigma2 has grabbed the input device. Stop it with `init 4`, then `init 3` afterwards. |
| High `reddedilen` (rejected) count | Writing to the wrong device. Pick the right one with `--aygit /dev/input/eventN`. |
| Load succeeds but keys do nothing | Enigma2 may have cached the old map: `init 4; sleep 5; init 3`. |
| Keys die again after a reboot | Boot hook missing — check with `ls -l /etc/rcS.d/S99next-kumanda`. |
| Some keys work, others don't | The dead ones likely use a different device address — see the warning at the top of your keymap. |

Log file: `/var/log/next-kumanda.log`

To uninstall:

```bash
python3 kur.py --kaldir
```

## Requirements

- An Enigma2 receiver with root access (telnet/SSH + FTP)
- Python 3 on the receiver (present in every image)
- The infrared receiver's input device under `/dev/input/event*`

No external Python packages required.

## Contributing

If you've recorded a keymap for your own box, add it under `keymaps/` and open a PR. Name the file `brand_model.keymap` and put the device address and image info in a comment at the top.

> Note: the code, comments and script output are in Turkish. The command-line interface is simple enough to follow from the examples above; issues and pull requests are welcome in either language.

---

## Lisans · License

MIT
