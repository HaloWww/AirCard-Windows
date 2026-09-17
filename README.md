# AirCard (Windows Port) 🎴

> **Native Windows port of [AirCard](https://github.com/mak5er/AirCard) by [@mak5er](https://github.com/mak5er)**  
> Customizes Apple Wallet & Apple Pay card skins on Windows without jailbreak.  
> **Tested on iOS 17 & 18.**  
> Powered by the `airlift` AirTraffic sync exploit.

---

## About This Port

The original [AirCard](https://github.com/mak5er/AirCard) application was created by **[@mak5er](https://github.com/mak5er)** for macOS (Swift / AppKit).

This repository is an independent Windows port that brings the card skinning engine to Windows. It interfaces directly with official 64-bit Apple Mobile Device DLLs (`AirTrafficHost.dll`, `MobileDevice.dll`, `CoreFoundation.dll`) from iTunes and `pymobiledevice3` to perform the AirTraffic sync escape natively on Windows without needing a Mac.


---

## Requirements
- **Windows 10 / 11 (64-bit)**
- **iTunes for Windows (64-bit)** (Standard installer from Apple, ensuring `Apple Mobile Device Support` is installed).
- **Python 3.10+ (64-bit)**

---

## Installation & Quick Start

1. Clone or download this repository:
   ```cmd
   git clone https://github.com/alrrstd/AirCard-Windows.git
   cd AirCard-Windows
   ```
2. Double-click **`AirCard.vbs`** (silent launch) or **`run_aircard.bat`**.  
   *On first launch, it will automatically configure the environment and launch the modern graphical interface.*

> **Prefer Terminal CLI?** You can launch the interactive console interface at any time with:  
> `run_aircard.bat --cli` or `python main.py`

---

## How to Customize Apple Wallet Cards

1. Connect your iPhone to your Windows PC via USB cable, unlock it, and tap **"Trust this Computer"**.
2. Launch AirCard via **`AirCard.vbs`** or **`run_aircard.bat`**.
3. **Card Detection**:
   - If your card was scanned before, select it from the dropdown.
   - Or click **"Scan via iPhone"**, double-click your iPhone's Side/Power button to invoke Apple Pay, and tap your card — AirCard will detect it automatically!
4. **Choose Skin**:
   - Click directly on the preview card, click **"Browse File..."**, or press **`Ctrl+V`** to paste any image from clipboard (PNG/JPG/WebP, 1536 × 969 px recommended).
5. Click **"Flash Skin to iPhone"**.
6. Once completed, open the **Apple Wallet** app on your iPhone or double-click the side button to enjoy your custom card design!

---

## Credits & Original Author

- **Original macOS Application:** **[@mak5er](https://github.com/mak5er)** ([AirCard Repository](https://github.com/mak5er/AirCard))
- **Contributor:** **[@Lumid-Off](https://github.com/Lumid-Off)**
- **Exploit:** Based on the `airlift` AirTraffic sync escape research.
- **Windows Implementation:** Python + ctypes bridge to official Apple Mobile Device DLLs & `pymobiledevice3`.
