  // → domínio Billing/Auth extraído para `static/src/38-billing-auth.js` (RFC 478, Issue 545)

  // ── Theme Toggle ─────────────────────────────────────────────────────
  // Persists the light/dark preference and toggles the <html data-theme>
  // attribute consumed by the CSS :root[data-theme='light'] selectors.
  // Dark = attribute absent (null) — matches the E2E theme test assertions.
  const THEME_STORAGE_KEY = '_cypher65_theme';

  function themeApply(pref) {
    const isLight = pref === 'light';
    const root = document.documentElement;
    if (isLight) root.setAttribute('data-theme', 'light');
    else root.removeAttribute('data-theme');
  }

  function themeCurrent() {
    return document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  }

  function themeToggle() {
    const next = themeCurrent() === 'light' ? 'dark' : 'light';
    themeApply(next);
    try { localStorage.setItem(THEME_STORAGE_KEY, next); } catch (e) { /* storage unavailable */ }
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.innerHTML = next === 'light' ? _ic('moon', 14) : _ic('sun', 14);
      btn.title = next === 'light' ? 'Switch to dark theme' : 'Switch to light theme';
    }
  }

  function initThemeToggle() {
    // Apply persisted preference on boot (fresh sessions default to dark).
    try {
      const saved = localStorage.getItem(THEME_STORAGE_KEY);
      themeApply(saved === 'light' ? 'light' : 'dark');
    } catch (e) { /* storage unavailable */ }
    const btn = document.getElementById('theme-toggle');
    if (btn) {
      btn.addEventListener('click', function() { themeToggle(); });
      btn.innerHTML = themeCurrent() === 'light' ? _ic('moon', 14) : _ic('sun', 14);
    }
  }

  // ── WebLN detection ───────────────────────────────────────────────────
  var _weblnProvider = null;
  var _weblnConnecting = false;

  function detectWebLN(timeout) {
    timeout = timeout || 3000;
    return new Promise(function(resolve) {
      if (window.webln && typeof window.webln.enable === 'function') {
        resolve(window.webln);
        return;
      }
      var handler = function() {
        document.removeEventListener('webln:ready', handler);
        resolve(window.webln || null);
      };
      document.addEventListener('webln:ready', handler, { once: true });
      setTimeout(function() {
        document.removeEventListener('webln:ready', handler);
        resolve(window.webln || null);
      }, timeout);
    });
  }

  async function connectWebLN() {
    if (_weblnConnecting) return;
    _weblnConnecting = true;
    var statusEl = document.getElementById('webln-status');
    var previewEl = document.getElementById('webln-preview');
    if (!statusEl || !previewEl) { _weblnConnecting = false; return; }

    statusEl.textContent = '\uD83D\uDD0D Detecting Lightning wallet...';
    statusEl.className = 'webln-status webln-status--pending';

    var provider = await detectWebLN(4000);
    if (!provider) {
      statusEl.textContent = '\u26A0 No WebLN wallet detected. Install Alby or Joule browser extension.';
      statusEl.className = 'webln-status webln-status--error';
      _weblnConnecting = false;
      return;
    }

    statusEl.textContent = '\uD83D\uDD11 Requesting permission...';
    try {
      await provider.enable();
    } catch (e) {
      statusEl.textContent = '\u26A0 Permission denied: ' + (e.message || 'user cancelled');
      statusEl.className = 'webln-status webln-status--error';
      _weblnConnecting = false;
      return;
    }

    statusEl.textContent = '\uD83D\uDCE1 Fetching node info...';
    try {
      var info = await provider.getInfo();
      var nodeAlias = info.node && info.node.alias ? info.node.alias : 'Unknown Node';
      var nodePubkey = info.node && info.node.pubkey ? info.node.pubkey : '';
      var lnAddr = info.node && info.node.lightning_address ? info.node.lightning_address : '';
      _weblnProvider = provider;

      previewEl.style.display = 'block';
      previewEl.innerHTML =
        '<div class="webln-preview__header">\u26A1 Lightning Wallet Detected</div>' +
        '<div class="webln-preview__body">' +
          '<div class="webln-preview__row"><span class="webln-preview__label">Provider</span><span class="webln-preview__val">' + escapeHtml(info.providerName || info.node && info.node.alias || 'WebLN') + '</span></div>' +
          '<div class="webln-preview__row"><span class="webln-preview__label">Node</span><span class="webln-preview__val">' + escapeHtml(nodeAlias) + '</span></div>' +
          (nodePubkey ? '<div class="webln-preview__row"><span class="webln-preview__label">Pubkey</span><span class="webln-preview__val mono">' + escapeHtml(fmt.shortAddr(nodePubkey)) + '</span></div>' : '') +
          (lnAddr ? '<div class="webln-preview__row"><span class="webln-preview__label">LN Addr</span><span class="webln-preview__val mono">' + escapeHtml(lnAddr) + '</span></div>' : '') +
        '</div>' +
        '<div class="webln-preview__actions">' +
          '<button class="btn btn--primary" id="webln-confirm-btn">\u2713 CONFIRM & CONNECT</button>' +
          '<button class="btn" id="webln-cancel-btn">\u2715 CANCEL</button>' +
        '</div>';

      statusEl.textContent = '\u2713 WebLN wallet ready — review and confirm';
      statusEl.className = 'webln-status webln-status--success';

      document.getElementById('webln-confirm-btn')?.addEventListener('click', function() {
        var btcAddr = info.walletAddress || '';
        if (btcAddr && dom.walletAddressInput) {
          dom.walletAddressInput.value = btcAddr;
          var evt = new Event('input', { bubbles: true });
          dom.walletAddressInput.dispatchEvent(evt);
          setTimeout(function() { dom.walletSave?.click(); }, 300);
        } else {
          statusEl.textContent = '\u2139 Your LN wallet did not provide a BTC address. Enter it manually above.';
          statusEl.className = 'webln-status webln-status--info';
          previewEl.style.display = 'none';
          _weblnProvider = null;
          setTimeout(function() { dom.walletAddressInput?.focus(); }, 100);
        }
      });
      document.getElementById('webln-cancel-btn')?.addEventListener('click', function() {
        previewEl.style.display = 'none';
        previewEl.innerHTML = '';
        statusEl.textContent = '';
        statusEl.className = 'webln-status';
        _weblnProvider = null;
        _weblnConnecting = false;
      });

    } catch (e) {
      statusEl.textContent = '\u26A0 Failed to get node info: ' + (e.message || 'unknown error');
      statusEl.className = 'webln-status webln-status--error';
    }
    _weblnConnecting = false;
  }

  // ── Bitcoin address validation (Bech32 + Base58Check) ──────────────
  const _BECH32_CHARSET = 'qpzry9x8gf2tvdw0s3jn54khce6mua7l';
  const _VALIDATE_BASE58 = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';

  function _bech32Polymod(values) {
    var GEN = [0x3b6a57b2, 0x26508e6d, 0x1ea119fa, 0x3d4233dd, 0x2a1462b3];
    var chk = 1;
    for (var i = 0; i < values.length; i++) {
      var top = chk >> 25;
      chk = ((chk & 0x1ffffff) << 5) ^ values[i];
      for (var j = 0; j < 5; j++) {
        if ((top >> j) & 1) chk ^= GEN[j];
      }
    }
    return chk;
  }

  // ── Real-time wallet address validation ──
  var _walletValidationTimer = null;
  function _updateWalletValidation() {
    var input = dom.walletAddressInput;
    var statusEl = document.getElementById('wallet-validation-status');
    if (!input || !statusEl) return;
    var addr = input.value.trim();
    if (!addr) {
      statusEl.textContent = '';
      statusEl.className = 'wallet-validation-status';
      input.classList.remove('field__input--valid', 'field__input--invalid');
      return;
    }
    var result = validateBitcoinAddress(addr);
    if (result.valid) {
      input.classList.remove('field__input--invalid');
      input.classList.add('field__input--valid');
      var typeLabel = addr.indexOf('bc1') === 0 ? 'Bech32' : 'Base58';
      statusEl.textContent = '\u2713 Valid ' + typeLabel + ' address';
      statusEl.className = 'wallet-validation-status wallet-validation-status--valid';
    } else {
      input.classList.remove('field__input--valid');
      input.classList.add('field__input--invalid');
      statusEl.textContent = '\u2717 ' + result.error;
      statusEl.className = 'wallet-validation-status wallet-validation-status--invalid';
    }
  }

  // Wire up real-time validation on input + debounced keyup
  dom.walletAddressInput?.addEventListener('input', _updateWalletValidation);
  dom.walletAddressInput?.addEventListener('keyup', function() {
    if (_walletValidationTimer) clearTimeout(_walletValidationTimer);
    _walletValidationTimer = setTimeout(_updateWalletValidation, 200);
  });

  function validateBitcoinAddress(addr) {
    if (!addr || typeof addr !== 'string') return { valid: false, error: 'Address is required' };
    addr = addr.trim();
    if (addr.length < 26 || addr.length > 90) return { valid: false, error: 'Invalid length (' + addr.length + ' chars)' };

    // FULL & FREE whitelist: every greeted wallet (WALLET_GREETINGS keys) is
    // entitled, so its exact address is accepted even when it doesn't match
    // the strict BTC prefix rules (e.g. the DOGE/LTC addresses). Only the
    // exact greeted addresses bypass — everything else is validated strictly.
    if (walletGreeting(addr)) return { valid: true, note: 'FULL & FREE wallet' };

    // Bech32 (bc1...)
    if (addr.indexOf('bc1') === 0 || addr.indexOf('BC1') === 0) {
      var lower = addr.toLowerCase();
      var pos = lower.lastIndexOf('1');
      if (pos < 1 || pos + 7 > lower.length) return { valid: false, error: 'Invalid Bech32 format' };
      var hrp = lower.slice(0, pos);
      var data = lower.slice(pos + 1);
      if (hrp !== 'bc') return { valid: false, error: 'Invalid prefix (expected bc1)' };
      if (data.length < 6) return { valid: false, error: 'Data part too short' };
      for (var i = 0; i < data.length; i++) {
        if (_BECH32_CHARSET.indexOf(data[i]) === -1) return { valid: false, error: 'Invalid Bech32 character' };
      }
      var values = [];
      for (var j = 0; j < data.length; j++) values.push(_BECH32_CHARSET.indexOf(data[j]));
      var hrpExpand = [];
      for (var k = 0; k < hrp.length; k++) hrpExpand.push(hrp.charCodeAt(k) >> 5);
      hrpExpand.push(0);
      for (var l = 0; l < hrp.length; l++) hrpExpand.push(hrp.charCodeAt(l) & 31);
      var all = hrpExpand.concat(values);
      if (_bech32Polymod(all) !== 1) return { valid: false, error: 'Invalid Bech32 checksum' };
      return { valid: true };
    }

    // Base58Check (1... or 3...)
    if (addr.indexOf('1') === 0 || addr.indexOf('3') === 0) {
      for (var m = 0; m < addr.length; m++) {
        if (_VALIDATE_BASE58.indexOf(addr[m]) === -1) return { valid: false, error: 'Invalid Base58 character' };
      }
      // Decode Base58 to hex and verify checksum
      try {
        var n = 0n;
        for (var p = 0; p < addr.length; p++) {
          n = n * 58n + BigInt(_VALIDATE_BASE58.indexOf(addr[p]));
        }
        var hex = n.toString(16);
        if (hex.length % 2 === 1) hex = '0' + hex;
        // Count leading '1's (each = leading zero byte)
        var lead1 = 0;
        while (lead1 < addr.length && addr[lead1] === '1') lead1++;
        if (lead1 > 0) hex = '00'.repeat(lead1) + hex;
        if (hex.length < 10) return { valid: false, error: 'Address too short for checksum' };
        var payload = hex.slice(0, hex.length - 8);
        var checksum = hex.slice(hex.length - 8);
        // We'd need SHA256 here, but can't in pure JS without crypto subtle
        // For now, do a basic format check and let backend do full checksum
        return { valid: true, note: 'Format OK — backend will verify checksum' };
      } catch (e) {
        return { valid: false, error: 'Invalid Base58 format' };
      }
    }

    return { valid: false, error: 'Address must start with bc1, 1, or 3' };
  }

  // ══════════════════════════════════════════════════════════════════════
  //  P0-4 · QR CODE CORE — ISO/IEC 18004, byte mode, versions 1-10
  //  Pure functions (no DOM) — mirrored in tests/test_app_js_core.js and
  //  validated cell-by-cell against golden matrices produced by the
  //  independent Kazuhiko Arase QRCode implementation (MIT-licensed, the
  //  vendor inside qrcode-terminal). All ECC levels L/M/Q/H supported;
  //  any valid BTC address (<= 90 chars) fits version <= 10.
  // ══════════════════════════════════════════════════════════════════════
  const QR_ECC = { L: 1, M: 0, Q: 3, H: 2 }; // values = 2-bit format field
  const QR_MODE_8BIT = 4;
  const QR_PAD0 = 0xEC, QR_PAD1 = 0x11;
  // GF(256) tables (primitive poly x^8+x^4+x^3+x^2+1)
  const QR_EXP = new Array(256), QR_LOG = new Array(256);
  (function buildQrMath() {
    for (let i = 0; i < 8; i++) QR_EXP[i] = 1 << i;
    for (let i = 8; i < 256; i++) QR_EXP[i] = QR_EXP[i - 4] ^ QR_EXP[i - 5] ^ QR_EXP[i - 6] ^ QR_EXP[i - 8];
    for (let i = 0; i < 255; i++) QR_LOG[QR_EXP[i]] = i;
  })();
  function qrGexp(n) { while (n < 0) n += 255; while (n >= 256) n -= 255; return QR_EXP[n]; }
  function qrGlog(n) { if (n < 1) throw new Error('qr glog(' + n + ')'); return QR_LOG[n]; }

  // Polynomial over GF(256) with leading-zero trim + shift (Arase semantics)
  function QrPoly(num, shift) {
    let offset = 0;
    while (offset < num.length && num[offset] === 0) offset++;
    this.num = new Array(num.length - offset + shift);
    for (let i = 0; i < num.length - offset; i++) this.num[i] = num[i + offset];
  }
  QrPoly.prototype.get = function (i) { return this.num[i]; };
  QrPoly.prototype.getLength = function () { return this.num.length; };
  QrPoly.prototype.multiply = function (e) {
    const num = new Array(this.getLength() + e.getLength() - 1);
    for (let i = 0; i < this.getLength(); i++) {
      for (let j = 0; j < e.getLength(); j++) {
        num[i + j] ^= qrGexp(qrGlog(this.get(i)) + qrGlog(e.get(j)));
      }
    }
    return new QrPoly(num, 0);
  };
  QrPoly.prototype.mod = function (e) {
    if (this.getLength() - e.getLength() < 0) return this;
    const ratio = qrGlog(this.get(0)) - qrGlog(e.get(0));
    const num = new Array(this.getLength());
    for (let i = 0; i < this.getLength(); i++) num[i] = this.get(i);
    for (let x = 0; x < e.getLength(); x++) num[x] ^= qrGexp(qrGlog(e.get(x)) + ratio);
    return new QrPoly(num, 0).mod(e);
  };

  // RS block table: rows are [L, M, Q, H] per version (v1-v10)
  const QR_RS_BLOCKS = [
    [1, 26, 19], [1, 26, 16], [1, 26, 13], [1, 26, 9],
    [1, 44, 34], [1, 44, 28], [1, 44, 22], [1, 44, 16],
    [1, 70, 55], [1, 70, 44], [2, 35, 17], [2, 35, 13],
    [1, 100, 80], [2, 50, 32], [2, 50, 24], [4, 25, 9],
    [1, 134, 108], [2, 67, 43], [2, 33, 15, 2, 34, 16], [2, 33, 11, 2, 34, 12],
    [2, 86, 68], [4, 43, 27], [4, 43, 19], [4, 43, 15],
    [2, 98, 78], [4, 49, 31], [2, 32, 14, 4, 33, 15], [4, 39, 13, 1, 40, 14],
    [2, 121, 97], [2, 60, 38, 2, 61, 39], [4, 40, 18, 2, 41, 19], [4, 40, 14, 2, 41, 15],
    [2, 146, 116], [3, 58, 36, 2, 59, 37], [4, 36, 16, 4, 37, 17], [4, 36, 12, 4, 37, 13],
    [2, 86, 68, 2, 87, 69], [4, 69, 43, 1, 70, 44], [6, 43, 19, 2, 44, 20], [6, 43, 15, 2, 44, 16],
  ];
  function qrGetRsBlocks(type, ecl) {
    const row = QR_RS_BLOCKS[(type - 1) * 4 + ({ 1: 0, 0: 1, 3: 2, 2: 3 })[ecl]];
    const list = [];
    for (let i = 0; i < row.length / 3; i++) {
      const count = row[i * 3], total = row[i * 3 + 1], data = row[i * 3 + 2];
      for (let j = 0; j < count; j++) list.push({ totalCount: total, dataCount: data });
    }
    return list;
  }

  const QR_PATTERN_POS = [
    [], [6, 18], [6, 22], [6, 26], [6, 30], [6, 34], [6, 22, 38], [6, 24, 42], [6, 26, 46], [6, 28, 50],
  ];
  const QR_G15 = (1 << 10) | (1 << 8) | (1 << 5) | (1 << 4) | (1 << 2) | (1 << 1) | (1 << 0);
  const QR_G18 = (1 << 12) | (1 << 11) | (1 << 10) | (1 << 9) | (1 << 8) | (1 << 5) | (1 << 2) | (1 << 0);
  const QR_G15_MASK = (1 << 14) | (1 << 12) | (1 << 10) | (1 << 4) | (1 << 1);
  function qrBchDigit(d) { let n = 0; while (d !== 0) { n++; d >>>= 1; } return n; }
  function qrBchTypeInfo(data) {
    let d = data << 10;
    while (qrBchDigit(d) - qrBchDigit(QR_G15) >= 0) d ^= QR_G15 << (qrBchDigit(d) - qrBchDigit(QR_G15));
    return ((data << 10) | d) ^ QR_G15_MASK;
  }
  function qrBchTypeNumber(data) {
    let d = data << 12;
    while (qrBchDigit(d) - qrBchDigit(QR_G18) >= 0) d ^= QR_G18 << (qrBchDigit(d) - qrBchDigit(QR_G18));
    return (data << 12) | d;
  }
  function qrGetMask(mask, i, j) {
    switch (mask) {
      case 0: return (i + j) % 2 === 0;
      case 1: return i % 2 === 0;
      case 2: return j % 3 === 0;
      case 3: return (i + j) % 3 === 0;
      case 4: return (Math.floor(i / 2) + Math.floor(j / 3)) % 2 === 0;
      case 5: return (i * j) % 2 + (i * j) % 3 === 0;
      case 6: return ((i * j) % 2 + (i * j) % 3) % 2 === 0;
      case 7: return ((i * j) % 3 + (i + j) % 2) % 2 === 0;
      default: throw new Error('bad maskPattern:' + mask);
    }
  }
  function qrErrorCorrectPoly(len) {
    let a = new QrPoly([1], 0);
    for (let i = 0; i < len; i++) a = a.multiply(new QrPoly([1, qrGexp(i)], 0));
    return a;
  }
  function qrLengthInBits(type) { return type < 10 ? 8 : 16; }

  function qrCreateData(type, ecl, text) {
    const blocks = qrGetRsBlocks(type, ecl);
    let totalData = 0;
    blocks.forEach(b => { totalData += b.dataCount; });
    const bits = [];
    let bitLen = 0;
    function put(num, len) {
      for (let i = 0; i < len; i++) {
        bits.push(((num >>> (len - i - 1)) & 1) === 1);
        bitLen++;
      }
    }
    put(QR_MODE_8BIT, 4);
    put(text.length, qrLengthInBits(type));
    for (let i = 0; i < text.length; i++) put(text.charCodeAt(i) & 0xff, 8);
    if (bitLen + 4 <= totalData * 8) put(0, 4);
    while (bitLen % 8 !== 0) put(0, 1);
    while (true) {
      if (bitLen >= totalData * 8) break;
      put(QR_PAD0, 8);
      if (bitLen >= totalData * 8) break;
      put(QR_PAD1, 8);
    }
    const buf = [];
    for (let i = 0; i < bits.length; i += 8) {
      let byte = 0;
      for (let j = 0; j < 8; j++) byte = (byte << 1) | (bits[i + j] ? 1 : 0);
      buf.push(byte);
    }
    let offset = 0, maxDc = 0, maxEc = 0;
    const dcdata = [], ecdata = [];
    for (let r = 0; r < blocks.length; r++) {
      const dcCount = blocks[r].dataCount;
      const ecCount = blocks[r].totalCount - dcCount;
      maxDc = Math.max(maxDc, dcCount);
      maxEc = Math.max(maxEc, ecCount);
      const dc = [];
      for (let i = 0; i < dcCount; i++) dc.push(buf[i + offset]);
      offset += dcCount;
      const rsPoly = qrErrorCorrectPoly(ecCount);
      const rawPoly = new QrPoly(dc, rsPoly.getLength() - 1);
      const modPoly = rawPoly.mod(rsPoly);
      const ec = new Array(rsPoly.getLength() - 1);
      for (let x = 0; x < ec.length; x++) {
        const modIndex = x + modPoly.getLength() - ec.length;
        ec[x] = modIndex >= 0 ? modPoly.get(modIndex) : 0;
      }
      dcdata[r] = dc; ecdata[r] = ec;
    }
    let total = 0;
    blocks.forEach(b => { total += b.totalCount; });
    const data = new Array(total);
    let index = 0;
    for (let z = 0; z < maxDc; z++) for (let s = 0; s < blocks.length; s++) if (z < dcdata[s].length) data[index++] = dcdata[s][z];
    for (let z = 0; z < maxEc; z++) for (let s = 0; s < blocks.length; s++) if (z < ecdata[s].length) data[index++] = ecdata[s][z];
    return data;
  }

  function qrMakeImpl(type, ecl, test, mask, data) {
    const mc = type * 4 + 17;
    const mods = [];
    for (let r = 0; r < mc; r++) { mods[r] = new Array(mc); for (let c = 0; c < mc; c++) mods[r][c] = null; }
    function probe(row, col) {
      for (let r = -1; r <= 7; r++) {
        if (row + r <= -1 || mc <= row + r) continue;
        for (let c = -1; c <= 7; c++) {
          if (col + c <= -1 || mc <= col + c) continue;
          mods[row + r][col + c] =
            ((0 <= r && r <= 6 && (c === 0 || c === 6)) ||
             (0 <= c && c <= 6 && (r === 0 || r === 6)) ||
             (2 <= r && r <= 4 && 2 <= c && c <= 4));
        }
      }
    }
    probe(0, 0); probe(mc - 7, 0); probe(0, mc - 7);
    const pos = QR_PATTERN_POS[type - 1];
    for (let i = 0; i < pos.length; i++) {
      for (let j = 0; j < pos.length; j++) {
        const row = pos[i], col = pos[j];
        if (mods[row][col] !== null) continue;
        for (let r = -2; r <= 2; r++) {
          for (let c = -2; c <= 2; c++) {
            mods[row + r][col + c] = (Math.abs(r) === 2 || Math.abs(c) === 2 || (r === 0 && c === 0));
          }
        }
      }
    }
    for (let r = 8; r < mc - 8; r++) if (mods[r][6] === null) mods[r][6] = (r % 2 === 0);
    for (let c = 8; c < mc - 8; c++) if (mods[6][c] === null) mods[6][c] = (c % 2 === 0);
    const fbits = qrBchTypeInfo((ecl << 3) | mask);
    for (let v = 0; v < 15; v++) {
      const mod = !test && (((fbits >> v) & 1) === 1);
      if (v < 6) mods[v][8] = mod;
      else if (v < 8) mods[v + 1][8] = mod;
      else mods[mc - 15 + v][8] = mod;
    }
    for (let h = 0; h < 15; h++) {
      const mod = !test && (((fbits >> h) & 1) === 1);
      if (h < 8) mods[8][mc - h - 1] = mod;
      else if (h < 9) mods[8][15 - h - 1 + 1] = mod;
      else mods[8][15 - h - 1] = mod;
    }
    mods[mc - 8][8] = !test;
    if (type >= 7) {
      const vbits = qrBchTypeNumber(type);
      for (let i = 0; i < 18; i++) {
        const mod = !test && (((vbits >> i) & 1) === 1);
        mods[Math.floor(i / 3)][i % 3 + mc - 8 - 3] = mod;
      }
      for (let x = 0; x < 18; x++) {
        const mod = !test && (((vbits >> x) & 1) === 1);
        mods[x % 3 + mc - 8 - 3][Math.floor(x / 3)] = mod;
      }
    }
    let inc = -1, row = mc - 1, bitIndex = 7, byteIndex = 0;
    for (let col = mc - 1; col > 0; col -= 2) {
      if (col === 6) col--;
      while (true) {
        for (let c = 0; c < 2; c++) {
          if (mods[row][col - c] === null) {
            let dark = false;
            if (byteIndex < data.length) dark = (((data[byteIndex] >>> bitIndex) & 1) === 1);
            if (qrGetMask(mask, row, col - c)) dark = !dark;
            mods[row][col - c] = dark;
            bitIndex--;
            if (bitIndex === -1) { byteIndex++; bitIndex = 7; }
          }
        }
        row += inc;
        if (row < 0 || mc <= row) { row -= inc; inc = -inc; break; }
      }
    }
    return mods;
  }

  function qrLostPoint(mods) {
    const mc = mods.length;
    let lp = 0;
    for (let row = 0; row < mc; row++) {
      for (let col = 0; col < mc; col++) {
        let sameCount = 0; const dark = mods[row][col];
        for (let r = -1; r <= 1; r++) {
          if (row + r < 0 || mc <= row + r) continue;
          for (let c = -1; c <= 1; c++) {
            if (col + c < 0 || mc <= col + c) continue;
            if (r === 0 && c === 0) continue;
            if (dark === mods[row + r][col + c]) sameCount++;
          }
        }
        if (sameCount > 5) lp += 3 + sameCount - 5;
      }
    }
    for (let row = 0; row < mc - 1; row++) {
      for (let col = 0; col < mc - 1; col++) {
        let count = 0;
        if (mods[row][col]) count++;
        if (mods[row + 1][col]) count++;
        if (mods[row][col + 1]) count++;
        if (mods[row + 1][col + 1]) count++;
        if (count === 0 || count === 4) lp += 3;
      }
    }
    for (let row = 0; row < mc; row++) {
      for (let col = 0; col < mc - 6; col++) {
        if (mods[row][col] && !mods[row][col + 1] && mods[row][col + 2] && mods[row][col + 3] && mods[row][col + 4] && !mods[row][col + 5] && mods[row][col + 6]) lp += 40;
      }
    }
    for (let col = 0; col < mc; col++) {
      for (let row = 0; row < mc - 6; row++) {
        if (mods[row][col] && !mods[row + 1][col] && mods[row + 2][col] && mods[row + 3][col] && mods[row + 4][col] && !mods[row + 5][col] && mods[row + 6][col]) lp += 40;
      }
    }
    let darkCount = 0;
    for (let col = 0; col < mc; col++) for (let row = 0; row < mc; row++) if (mods[row][col]) darkCount++;
    lp += Math.abs(100 * darkCount / mc / mc - 50) / 5 * 10;
    return lp;
  }

  // Public encode: returns { modules: 2D bool, size, type, ecl, mask }
  function qrEncode(text, ecl) {
    text = String(text || '');
    ecl = QR_ECC[ecl] !== undefined ? QR_ECC[ecl] : QR_ECC.M;
    let type = 1;
    for (type = 1; type <= 10; type++) {
      const blocks = qrGetRsBlocks(type, ecl);
      let totalData = 0;
      blocks.forEach(b => { totalData += b.dataCount; });
      const bitLen = 4 + qrLengthInBits(type) + text.length * 8;
      if (bitLen <= totalData * 8) break;
    }
    if (type > 10) throw new Error('QR input too long (' + text.length + ' chars)');
    const data = qrCreateData(type, ecl, text);
    let minLp = 0, pattern = 0;
    for (let i = 0; i < 8; i++) {
      const m = qrMakeImpl(type, ecl, true, i, data);
      const lp = qrLostPoint(m);
      if (i === 0 || minLp > lp) { minLp = lp; pattern = i; }
    }
    const modules = qrMakeImpl(type, ecl, false, pattern, data);
    return { modules, size: type * 4 + 17, type, ecl, mask: pattern };
  }

  // Render the module matrix as a crisp inline SVG (quiet zone = 4 modules)
  function qrSvg(modules) {
    const size = modules.length;
    const q = 4;
    const cells = [];
    for (let r = 0; r < size; r++) {
      for (let c = 0; c < size; c++) {
        if (modules[r][c]) cells.push('M' + (c + q) + ' ' + (r + q) + 'h1v1h-1z');
      }
    }
    const dim = size + q * 2;
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + dim + ' ' + dim + '" shape-rendering="crispEdges" role="img" aria-label="QR code">' +
      '<rect width="' + dim + '" height="' + dim + '" fill="' + cssVar('--text-primary') + '"/>' +
      (cells.length ? '<path d="' + cells.join('') + '" fill="' + cssVar('--bg-deep') + '"/>' : '') +
      '</svg>';
  }

  // ── P0-4 · Wallet identity: checksum split + health ──────────────────
  // Pure helpers mirrored in tests. walletAddressParts splits an address
  // into {type, prefix, body, checksum, full} so the UI can highlight the
  // checksum region (the classic wrong-address ticket killer).
  function walletAddressParts(addr) {
    if (!addr) return null;
    addr = String(addr).trim();
    if (!addr) return null;
    const lower = addr.toLowerCase();
    // Bech32: checksum is exactly the last 6 chars (BIP-173) — highlight them.
    if (lower.indexOf('bc1') === 0 && addr.length >= 10) {
      return { type: 'bech32', prefix: 'bc1', body: addr.slice(3, -6), checksum: addr.slice(-6), full: addr };
    }
    // Base58 (legacy/P2SH): the trailing chars are the check digits operators
    // compare against their wallet app — highlight the real trailing substring
    // (never a byte-derived string that would differ from the displayed address).
    if ((addr[0] === '1' || addr[0] === '3') && addr.length >= 8) {
      return { type: 'base58', prefix: addr[0], body: addr.slice(1, -6), checksum: addr.slice(-6), full: addr };
    }
    return { type: 'other', prefix: '', body: addr.length > 6 ? addr.slice(0, -6) : '', checksum: addr.slice(-6), full: addr };
  }

  // Wallet health from the live snapshot (honest: every check gates on real
  // observed data — never fabricates). Returns {status, score, checks, connected}.
  function walletHealth(snap, now) {
    snap = snap || {};
    now = now || Math.floor(Date.now() / 1000);
    const connected = !!snap.btc_address;
    const worker = snap.worker || {};
    const pool = snap.pool || {};
    const checks = [
      { key: 'connected', label: 'Address set', ok: connected },
      { key: 'fresh', label: 'Data fresh', ok: !!snap.ts && (now - snap.ts) < 300 },
      { key: 'worker', label: 'Worker found', ok: !!snap.worker },
      { key: 'hashing', label: 'Hashing', ok: Number(worker.hashrate || 0) > 0 },
      { key: 'share', label: 'Recent share', ok: !!worker.lastSubmission && (now - Number(worker.lastSubmission)) < 7200 },
      { key: 'pool', label: 'Pool responding', ok: !!snap.pool && !pool._stale },
    ];
    const passed = checks.filter(c => c.ok).length;
    const score = Math.round(passed / checks.length * 100);
    let status;
    if (!connected) status = 'NO_WALLET';
    else if (score >= 80) status = 'HEALTHY';
    else if (score >= 50) status = 'DEGRADED';
    else status = 'CRITICAL';
    return { status, score, checks, connected, passed };
  }

  // ── decode HTML entities (reverse of escapeHtml) ────────────────────
  function decodeHtmlEntities(s) {
    if (!s) return '';
    var txt = document.createElement('textarea');
    txt.innerHTML = String(s);
    return txt.value;
  }

  // ── normalize worker name: decode HTML + trim + lowercase ───────────
  function normalizeWorkerName(s) {
    return decodeHtmlEntities(String(s || '')).trim().toLowerCase();
  }

  // ── Professional value transition ──
  function smoothUpdate(el, newText) {
    if (!el) return;
    const old = el.textContent;
    if (old !== newText && old !== '\u2014' && newText !== '\u2014') {
      el.classList.remove('value-flash'); void el.offsetWidth; el.classList.add('value-flash');
    }
    el.textContent = newText;
  }

  // ── Count-up animation ──
  const _countUpState = new WeakMap();
  function _parseNum(txt) { if (!txt) return NaN; const m = String(txt).match(/([\d.,]+)/); if (!m) return NaN; return parseFloat(m[1].replace(/,/g, '')); }
  function countUpValue(el, targetText, durationMs) {
    durationMs = durationMs || 420;
    if (!el || window.matchMedia('(prefers-reduced-motion: reduce)').matches) { if (el) el.textContent = targetText; return; }
    const num = _parseNum(targetText);
    if (isNaN(num)) { el.textContent = targetText; return; }
    const prefix = String(targetText).replace(/^([^\d]*).*/, '$1');
    const suffix = String(targetText).replace(/^.*?([^\d]*)$/, '$1');
    const decimals = (String(targetText).match(/\.(\d+)/) || ['', ''])[1].length;
    const start = performance.now();
    const from = isNaN(_parseNum(el.textContent)) ? 0 : _parseNum(el.textContent);
    const existing = _countUpState.get(el);
    if (existing && existing.raf) cancelAnimationFrame(existing.raf);
    const step = () => {
      const t = Math.min(1, (performance.now() - start) / durationMs);
      const eased = 1 - Math.pow(1 - t, 3);
      const current = from + (num - from) * eased;
      el.textContent = prefix + current.toFixed(decimals) + suffix;
      if (t < 1) { const rafInner = requestAnimationFrame(step); _countUpState.set(el, { raf: rafInner }); }
      else { el.textContent = targetText; _countUpState.delete(el); }
    };
    const rafOuter = requestAnimationFrame(step);
  }

  // ── Skeleton loading (design-motion-principles) ──
  let _skeletonsHidden = false;
  // Shape set per container kind — header line + rows (chart/KPI variants).
  function _skelShapes(kind) {
    if (kind === 'kpi') return ['skel--kpi','skel--kpi','skel--kpi','skel--kpi'];
    if (kind === 'chart') return ['skel--chart','skel--line w-60','skel--line w-40'];
    if (kind === 'table') return ['skel--row','skel--row','skel--row','skel--row w-80','skel--row w-60'];
    return ['skel--line w-40','skel--line w-90','skel--line w-70','skel--line w-50'];
  }
  function _skelKind(p) {
    const id = (p && p.id) || '';
    if (p && p.classList.contains('kpi-row')) return 'kpi';
    if (id.indexOf('chart') !== -1 || id.indexOf('trend') !== -1) return 'chart';
    if (id.indexOf('market') !== -1) return 'table';  // offers grid dominates the panel
    if (id.indexOf('table') !== -1 || (p && p.classList.contains('rentals-list'))) return 'table';
    return '';
  }
  // Build a skeleton overlay INSIDE a container (used both at boot and for
  // lazy module loads). Decorative only — pointer-events:none, aria-hidden.
  function _skelBuild(container, kind) {
    if (container.querySelector('.skel-overlay')) return;
    const ov = document.createElement('div');
    ov.className = 'skel-overlay';
    ov.setAttribute('aria-hidden', 'true');
    _skelShapes(_skelKind(container) || kind).forEach(function (cls) {
      const s = document.createElement('div'); s.className = 'skel ' + cls;
      ov.appendChild(s);
    });
    container.appendChild(ov);
  }
  function skelShow(container, kind) { if (container) _skelBuild(container, kind); }

  // ── Flicker dedup (audit 18-Ago) ────────────────────────────────────────
  // renderMarketGrid / renderTerminalEvents / renderLeaderboard etc. wrote
  // innerHTML on EVERY 15s snapshot even when the rendered content was
  // byte-identical — destroying/recreating rows every poll ("infinite
  // blinking"). Same root cause the Command Center had (_lastCcKey fix);
  // generalize it: skip the DOM write when the serialized HTML matches the
  // last write for that element. WeakMap keyed by element keeps zero state
  // on window and auto-GCs. Returns true when the write happened.
  const _lastSetHtml = new WeakMap();
  function setHtmlIfChanged(el, html) {
    if (!el || typeof el.innerHTML !== 'string') return false;
    if (_lastSetHtml.get(el) === html) return false;
    _lastSetHtml.set(el, html);
    el.innerHTML = html;
    return true;
  }

  function skelHide(container) {
    if (!container) return;
    const ov = container.querySelector('.skel-overlay');
    if (ov) { ov.remove(); }
  }
  // Skeleton around an async load: show → await → hide. Reused by manual
  // refresh buttons and module re-activation when the panel is empty, so the
  // shimmer is identical to the boot skeleton (transform-only, Emil <300ms).
  function skelRefresh(container, kind, p) {
    if (!container) return Promise.resolve(p);
    skelShow(container, kind);
    return Promise.resolve(p).then(
      function (v) { skelHide(container); return v; },
      function (e) { skelHide(container); throw e; }
    );
  }
  function showSkeletons() {
    document.querySelectorAll('.panel').forEach(p => _skelBuild(p, ''));
    // KPI row is the most prominent loading surface — give it KPI-shaped
    // blocks too (review fix: the kpi branch was previously dead code).
    document.querySelectorAll('#kpi-row').forEach(k => _skelBuild(k, 'kpi'));
  }
  function hideSkeletons() {
    document.querySelectorAll('.skel-overlay').forEach(o => o.remove());
    _skeletonsHidden = true;
  }

  // ── Button loading state ──
  function setBtnLoading(btn, on) {
    if (!btn) return;
    btn.classList.toggle('is-loading', on);
    btn.disabled = on;
  }

  // ── Modal exit (Jakub: exit subtler than enter) ──
  // Add .modal--closing, wait for the 120ms fade, then drop .modal--open.
  // Pending close timers are tracked per-modal so a rapid reopen cancels the
  // exit (review fix: close → reopen within 140ms must not force-close).
  const _modalCloseTimers = new Map();
  function closeModalAnimated(modal) {
    if (!modal || !modal.classList.contains('modal--open')) return;
    if (_modalCloseTimers.has(modal)) return;
    const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    modal.classList.add('modal--closing');
    const timer = setTimeout(function () {
      _modalCloseTimers.delete(modal);
      modal.classList.remove('modal--closing');
      modal.classList.remove('modal--open');
    }, reduce ? 0 : 140);
    _modalCloseTimers.set(modal, timer);
  }
  // Open helper: cancels any pending close + clears the exit class so a modal
  // reopened mid-exit animates in (not out). Pure add otherwise.
  function openModalAnimated(modal) {
    if (!modal) return;
    const t = _modalCloseTimers.get(modal);
    if (t) { clearTimeout(t); _modalCloseTimers.delete(modal); }
    modal.classList.remove('modal--closing');
    modal.classList.add('modal--open');
  }

  // ══════════════════════════════════════════════════════════════════════
  // RENDER FUNCTIONS
  // ══════════════════════════════════════════════════════════════════════

  // ── HUD — fixed bar with critical metrics ──
  function renderHUD(snap) {
    const w = snap.worker || {};
    const pool = snap.pool || {};
    const prox = snap.proximity || {};
    const workers = snap.all_workers || [];

    if (!dom.hudBar) return;
    if (!snap.worker) { dom.hudBar.style.display = 'none'; return; }
    dom.hudBar.style.display = 'flex';
    // Idle worker (hr=0) still renders — bestDiff/lastSubmission/uptime visible

    if (dom.hudHashrate) dom.hudHashrate.textContent = fmt.hashrate(w.hashrate);
    if (dom.hudBestdiff) dom.hudBestdiff.textContent = fmt.diff(w.bestDifficulty);
    const shares = prox.live_calc?.session_totals?.shares_so_far || 0;
    if (dom.hudShares) dom.hudShares.textContent = shares.toLocaleString();
    if (dom.hudPoolhr) dom.hudPoolhr.textContent = fmt.hashrate(pool.hashrate);
  }

  function renderStatusBar(snap) {
    const w = snap.worker || {};
    const pool = snap.pool || {};
    const net = snap.network || {};
    const btc = snap.btc_price || {};
    const workers = snap.all_workers || [];
    const axeFleet = snap.axe_fleet || [];

    // System block
    if (dom.sbLed) {
      const isOnline = !!snap.worker;
      dom.statusBar?.classList.toggle('is-online', isOnline);
      dom.sbLed.style.background = isOnline ? 'var(--accent-green)' : 'var(--accent-red)';
    }
    if (dom.sbStatus) dom.sbStatus.textContent = snap.worker ? (snap.worker.hashrate ? 'ONLINE' : 'IDLE') : 'OFFLINE';
    if (dom.sbWorkers) dom.sbWorkers.textContent = `${workers.length} worker${workers.length === 1 ? '' : 's'}`;

    // Mining block
    if (dom.sbHashrate) dom.sbHashrate.textContent = fmt.hashrate(w.hashrate);
    if (dom.sbBestdiff) dom.sbBestdiff.textContent = fmt.diff(w.bestDifficulty);
    if (dom.sbLastshare) dom.sbLastshare.textContent = w.lastSubmission ? fmt.age(w.lastSubmission) : '\u2014';

    // Pool block
    if (dom.sbPoolHr) dom.sbPoolHr.textContent = fmt.hashrate(pool.hashrate);
    if (dom.sbPoolWorkers) dom.sbPoolWorkers.textContent = `${pool.workers || 0}`;
    // The pool API exposes the last block height under lastBlockTime (the
    // old lastBlock key no longer exists). Accept both for backward compat.
    const poolBlock = pool.lastBlock || pool.lastBlockTime;
    if (dom.sbPoolBlock) dom.sbPoolBlock.textContent = poolBlock ? `#${poolBlock.toLocaleString()}` : '\u2014';

    // Network block
    if (dom.sbNetDiff) dom.sbNetDiff.textContent = fmt.diff(net.difficulty);
    if (dom.sbNetPrice) dom.sbNetPrice.textContent = btc.usd ? `$${Number(btc.usd).toLocaleString()}` : '\u2014';
    if (dom.sbNetHeight) dom.sbNetHeight.textContent = net.height ? `#${net.height}` : '\u2014';
    _staleChip(dom.sbNetPrice, btc.stale, 'cache');
    _staleChip(dom.sbNetDiff, net.stale, 'cache');

    // Fleet block
    const online = axeFleet.filter(d => d.status === 'ONLINE').length;
    const total = axeFleet.length;
    if (dom.sbFleetOnline) dom.sbFleetOnline.textContent = online;
    if (dom.sbFleetTotal) dom.sbFleetTotal.textContent = total;
    let fleetHr = 0;
    axeFleet.forEach(d => { fleetHr += Number(d.hashrate || 0); });
    if (dom.sbFleetHr) dom.sbFleetHr.textContent = fleetHr > 0 ? fmt.hashrate(fleetHr) : '\u2014';

    // Wallet block — show connected BTC address from snapshot with the
    // checksum region highlighted (P0-4: the wrong-address ticket killer).
    // shortAddrChunk + a checksum span so the operator can visually verify
    // the trailing check digits against their own wallet app.
    if (dom.sbWalletAddr) {
      var addr = snap.btc_address || window.BTC_ADDRESS || '';
      if (addr) {
        var parts = walletAddressParts(addr);
        var ck = (parts && parts.checksum) ? parts.checksum : addr.slice(-6);
        var head = addr.length > 12 ? addr.slice(0, 6) : addr.slice(0, addr.length - 6);
        dom.sbWalletAddr.innerHTML = '<span title="' + escapeHtml(addr) + '">' + escapeHtml(head) + '…<span class="addr-ck">' + escapeHtml(ck) + '</span></span>';
      } else {
        dom.sbWalletAddr.innerHTML = '—';
      }
      dom.sbWalletAddr.title = addr || 'no wallet connected';
    }
    // Wallet connection state — only topbar button remains
    // Connection state tracked via localStorage.getItem('_wallet_connected')
  }

  // A single, quiet freshness signal for the operational shell. Individual
  // panels retain their detailed badges; this one prevents a stale network,
  // BTC price, pool, or entire snapshot from being missed while another module
  // is open. It deliberately does not animate because it can update every poll.
  // snapshotFreshness / snapshotFreshnessLabel live in 10-core-fmt.js (Issue #536)
  // so the age is always visible — LIVE / SYNCED / DADOS ANTIGOS / NO DATA.
  function renderSnapshotFreshness(snap) {
    const el = dom.topbarFreshness;
    if (!el) return;
    const freshness = snapshotFreshness(snap);
    const ageText = freshness.age === null ? 'idade desconhecida' : fmt.secsToHuman(freshness.age);
    const label = snapshotFreshnessLabel(freshness, ageText);
    el.hidden = !!label.hidden;
    el.textContent = label.text;
    el.classList.remove('topbar__freshness--live', 'topbar__freshness--synced', 'topbar__freshness--stale', 'topbar__freshness--mute');
    el.classList.add('topbar__freshness--' + label.tone);
    const sourceText = freshness.sources.length ? freshness.sources.join(', ') : 'snapshot';
    el.title = label.tone === 'stale'
      ? ('Dados desatualizados: ' + sourceText + ' · última atualização ' + ageText + ' atrás.')
      : ('Atualizado há ' + ageText + ' · ' + sourceText);
  }

  // ── Operational Overview (Issue 367) ─────────────────────────────────
  // Combines the real snapshot with the independently polled fleet health
  // endpoint. The model is pure and mirrored in the JS core suite. A missing
  // value remains unavailable — zero is shown only when the source proves it.
  let _operationalFleetData = null;
  let _operationalFleetError = false;

  function buildOperationalOverviewModel(snap, fleetData, fleetError, nowSec) {
    const data = snap || {};
    const fleet = fleetData && fleetData.fleet_stats;
    const devices = fleetData && Array.isArray(fleetData.device_health) ? fleetData.device_health : [];
    const freshness = snapshotFreshness(data, nowSec);
    const fleetAges = devices.map(function(d) {
      const raw = d && d.telemetry && d.telemetry.age_seconds;
      return raw === null || raw === undefined || raw === '' ? null : Number(raw);
    }).filter(function(v) { return v !== null && isFinite(v) && v >= 0; });
    const fleetAge = fleetAges.length ? Math.max.apply(null, fleetAges) : null;
    const fleetTelemetryStale = fleetAge !== null && fleetAge > 150;
    const staleSources = freshness.sources.slice();
    if (freshness.stale && freshness.sources.length === 0) staleSources.push('snapshot');
    if (fleetTelemetryStale) staleSources.push('fleet telemetry');
    // Combined freshness cannot be called LIVE when the snapshot has no
    // timestamp, even if the independently fetched Fleet samples are recent.
    const dataAge = freshness.age === null ? null : (fleetAge === null ? freshness.age : Math.max(freshness.age, fleetAge));
    const dataStale = freshness.stale || fleetTelemetryStale;

    const profit = data.profitability || {};
    const costValuePresent = profit.cost_per_day_usd !== null && profit.cost_per_day_usd !== undefined && profit.cost_per_day_usd !== '';
    const rawCost = Number(profit.cost_per_day_usd);
    const hasCost = profit.cost_model_configured === true && costValuePresent && isFinite(rawCost) && rawCost >= 0;

    const model = {
      loading: !fleet && !fleetError,
      fleetError: !!fleetError,
      empty: false,
      overall: 'LOADING',
      tone: 'neutral',
      health: 'WAITING',
      healthDetail: 'Reading fleet telemetry…',
      attention: null,
      attentionDetail: 'Waiting for devices…',
      lostHashrateHs: null,
      lossBaselineDevices: 0,
      costPerDayUsd: hasCost ? rawCost : null,
      costDetail: hasCost ? String(profit.cost_label || 'Configured cost model') : 'Cost model not configured',
      freshness: dataStale ? 'STALE' : (dataAge === null ? 'NO DATA' : 'LIVE'),
      dataAge: dataAge,
      freshnessDetail: staleSources.length ? staleSources.join(', ') : (dataAge === null ? 'Snapshot timestamp unavailable' : 'Snapshot and fleet telemetry'),
      actionTitle: 'WAIT FOR DATA',
      actionTarget: '',
      actionPanel: '',
      actionEnabled: false,
      stateText: 'Loading real operational data…',
    };

    if (fleetError) {
      model.loading = false;
      model.overall = 'UNAVAILABLE';
      model.tone = 'critical';
      model.health = 'UNAVAILABLE';
      model.healthDetail = 'Fleet health endpoint unavailable';
      model.attentionDetail = 'Cannot verify ASIC state';
      model.freshness = 'PARTIAL';
      model.freshnessDetail = 'Fleet telemetry unavailable';
      model.actionTitle = 'OPEN FLEET DIAGNOSTIC';
      model.actionTarget = 'fleet';
      model.actionPanel = 'axe-fleet-panel';
      model.actionEnabled = true;
      model.stateText = 'Fleet data could not be loaded. Snapshot metrics may still be current.';
      return model;
    }
    if (!fleet) return model;

    const total = Math.max(0, Number(fleet.total_devices) || 0);
    const offline = Math.max(0, Number(fleet.offline) || 0);
    const warning = Math.max(0, Number(fleet.warning) || 0);
    const online = Math.max(0, Number(fleet.online) || 0);
    const attention = offline + warning;
    const healthScore = Number(fleet.avg_health_score);
    const baselineCount = Math.max(0, Number(fleet.hashrate_loss_baseline_devices) || 0);
    const lost = Number(fleet.hashrate_lost_hs);
    model.loading = false;
    model.attention = attention;
    model.attentionDetail = warning + ' warning · ' + offline + ' offline';
    model.lossBaselineDevices = baselineCount;
    model.lostHashrateHs = baselineCount > 0 && isFinite(lost) && lost >= 0 ? lost : null;

    if (total === 0) {
      model.empty = true;
      model.overall = dataStale ? 'STALE DATA' : 'NO FLEET';
      model.tone = dataStale ? 'warning' : 'neutral';
      model.health = 'NO FLEET';
      model.healthDetail = 'No ASIC registered';
      model.attentionDetail = '0 registered devices';
      model.actionTitle = 'REGISTER OR DISCOVER ASIC';
      model.actionTarget = 'fleet';
      model.actionPanel = 'axe-fleet-panel';
      model.actionEnabled = true;
      model.stateText = 'No ASIC is registered; fleet health and hashrate loss cannot be calculated.';
      return model;
    }

    if (offline > 0 || (isFinite(healthScore) && healthScore < 30)) {
      model.overall = 'CRITICAL';
      model.tone = 'critical';
      model.health = 'CRITICAL';
    } else if (warning > 0 || (isFinite(healthScore) && healthScore < 60)) {
      model.overall = 'ATTENTION';
      model.tone = 'warning';
      model.health = 'DEGRADED';
    } else {
      model.overall = 'HEALTHY';
      model.tone = 'healthy';
      model.health = 'HEALTHY';
    }
    model.healthDetail = online + '/' + total + ' reachable · health ' + (isFinite(healthScore) ? Math.round(healthScore) + '/100' : 'unavailable');
    if (dataStale) {
      model.overall = 'STALE DATA';
      if (model.tone === 'healthy') model.tone = 'warning';
    }
    model.stateText = attention > 0
      ? attention + ' ASIC exception' + (attention === 1 ? '' : 's') + ' require operator diagnosis.'
      : (dataStale ? 'One or more operational sources are stale; verify data before deciding.' : 'Fleet telemetry is loaded and current.');

    // Exception-first action. Snapshot Command Center cards are advisory, but
    // this surface intentionally ignores external URLs and only navigates to
    // an internal diagnostic module. It cannot dispatch a device command.
    let action = null;
    if (dataStale) {
      action = fleetTelemetryStale
        ? { title: 'VERIFY STALE FLEET TELEMETRY', target: 'fleet', panel: 'axe-fleet-panel' }
        : { title: 'VERIFY STALE DATA SOURCES', target: 'dashboard', panel: staleSources.indexOf('rede') !== -1 || staleSources.indexOf('preço BTC') !== -1 ? 'network-panel' : 'pool-overview' };
    } else if (attention > 0) {
      action = { title: 'INSPECT ' + attention + ' ASIC EXCEPTION' + (attention === 1 ? '' : 'S'), target: 'fleet', panel: 'axe-fleet-panel' };
    } else {
      const cards = Array.isArray(data.command_center) ? data.command_center : [];
      const card = cards.find(function(c) {
        return c && c.target && c.id !== 'affiliate_buy' && !c.url;
      });
      if (card) action = { title: String(card.title || 'OPEN DIAGNOSTIC').toUpperCase(), target: String(card.target), panel: String(card.panel || '') };
    }
    if (!action && !hasCost) {
      action = { title: 'CONFIGURE OPERATIONAL COST', target: 'dashboard', panel: 'profit-panel' };
    }
    if (action) {
      model.actionTitle = action.title;
      model.actionTarget = action.target;
      model.actionPanel = action.panel;
      model.actionEnabled = true;
    } else {
      model.actionTitle = 'NO ACTION REQUIRED';
      model.stateText = dataStale ? 'Operation appears stable, but one or more data sources are stale.' : 'Operation is healthy and current; no operator action is required.';
    }
    return model;
  }

  function renderOperationalOverview(snap, fleetData, fleetError) {
    const root = document.getElementById('operational-overview');
    if (!root) return;
    const model = buildOperationalOverviewModel(snap, fleetData, fleetError);
    const put = function(id, value) { const node = document.getElementById(id); if (node) node.textContent = value; };
    root.setAttribute('aria-busy', model.loading ? 'true' : 'false');
    root.classList.toggle('is-critical', model.tone === 'critical');
    root.classList.toggle('is-warning', model.tone === 'warning');
    root.classList.toggle('is-healthy', model.tone === 'healthy');
    put('op-overall-status', model.overall);
    const badge = document.getElementById('op-overall-status');
    if (badge) badge.className = 'badge ' + (model.tone === 'critical' ? 'badge--red' : model.tone === 'warning' ? 'badge--amber' : model.tone === 'healthy' ? 'badge--green' : 'badge--mute');
    put('op-health', model.health);
    put('op-health-detail', model.healthDetail);
    put('op-attention', model.attention === null ? '—' : String(model.attention));
    put('op-attention-detail', model.attentionDetail);
    put('op-lost-hashrate', model.lostHashrateHs === null ? '—' : fmt.hashrate(model.lostHashrateHs));
    put('op-lost-hashrate-detail', model.lossBaselineDevices > 0 ? 'Baseline available for ' + model.lossBaselineDevices + ' ASIC' + (model.lossBaselineDevices === 1 ? '' : 's') : 'Baseline unavailable');
    put('op-cost', model.costPerDayUsd === null ? 'NOT CONFIGURED' : '$' + model.costPerDayUsd.toFixed(2) + '/day');
    put('op-cost-detail', model.costDetail);
    put('op-freshness', model.freshness + (model.dataAge === null ? '' : ' · ' + fmt.secsToHuman(model.dataAge)));
    put('op-freshness-detail', model.freshnessDetail);
    put('op-action-title', model.actionTitle);
    put('op-action-detail', model.actionEnabled ? 'Opens diagnostic only · no command is executed' : 'Advisory only · no command is executed');
    put('op-state', model.stateText);
    const action = document.getElementById('op-action');
    if (action) {
      action.disabled = !model.actionEnabled;
      action.dataset.target = model.actionTarget;
      action.dataset.panel = model.actionPanel;
      action.textContent = model.actionEnabled ? 'OPEN DIAGNOSTIC' : 'NO ACTION';
    }
  }

  function initOperationalOverviewControls() {
    const action = document.getElementById('op-action');
    if (!action) return;
    action.addEventListener('click', function() {
      if (action.disabled) return;
      const target = action.dataset.target || '';
      const panel = action.dataset.panel || '';
      if (target) activateModule(target);
      if (panel) {
        setTimeout(function() {
          const node = document.getElementById(panel);
          if (!node) return;
          const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
          node.scrollIntoView({ behavior: reduceMotion ? 'auto' : 'smooth', block: 'start' });
          node.focus && node.focus({ preventScroll: true });
        }, 140);
      }
    });
  }

  // ── P0-4 · Wallet identity card (QR + checksum + health) ─────────────
  // Renders the CONNECT WALLET modal's WALLET IDENTITY block: a scannable
  // QR of the full address, the address with its checksum highlighted, a
  // copy button and a live health strip computed from the snapshot.
  function renderWalletIdentity(snap) {
    var box = document.getElementById('wallet-id');
    if (!box) return;
    var addr = (snap && snap.btc_address) || window.BTC_ADDRESS || '';
    if (!addr) {
      box.style.display = 'none';
      return;
    }
    box.style.display = '';
    // QR (pure JS encoder — no external service, address never leaves browser).
    // setHtmlIfChanged: the QR SVG is byte-identical for the same address, so
    // re-encoding on every 15s poll made the identity card visibly flicker.
    var qrBox = document.getElementById('wallet-id-qr');
    if (qrBox) {
      try {
        var qr = qrEncode(addr, 'M');
        setHtmlIfChanged(qrBox, qrSvg(qr.modules));
      } catch (e) {
        setHtmlIfChanged(qrBox, '<div class="wallet-id__qr-error">QR unavailable</div>');
      }
    }
    // Checksum-highlighted address
    var addrEl = document.getElementById('wallet-id-addr');
    if (addrEl) {
      var parts = walletAddressParts(addr);
      if (parts) {
        setHtmlIfChanged(addrEl, '<span class="addr-pfx">' + escapeHtml(parts.prefix) + '</span>' +
          '<span class="addr-body">' + escapeHtml(parts.body) + '</span>' +
          '<span class="addr-ck">' + escapeHtml(parts.checksum) + '</span>');
      } else {
        addrEl.textContent = addr;
      }
    }
    // Copy button
    var copyBtn = document.getElementById('wallet-id-copy');
    if (copyBtn) {
      copyBtn.onclick = function() {
        if (navigator.clipboard && addr) {
          navigator.clipboard.writeText(addr).then(function() {
            var orig = copyBtn.textContent;
            copyBtn.textContent = '[copied]';
            setTimeout(function() { copyBtn.textContent = orig; }, 1800);
          });
        }
      };
    }
    // Health strip
    var health = walletHealth(snap || {});
    var hEl = document.getElementById('wallet-id-health');
    if (hEl) {
      hEl.className = 'wallet-id__health wallet-id__health--' + health.status.toLowerCase();
      hEl.textContent = health.connected
        ? health.status + ' · ' + health.score + '% (' + health.passed + '/' + health.checks.length + ' checks)'
        : 'NO WALLET CONNECTED';
      hEl.title = health.checks.map(function(c) { return (c.ok ? '✓' : '✗') + ' ' + c.label; }).join('\n');
    }
    var checksEl = document.getElementById('wallet-id-checks');
    if (checksEl && health.connected) {
      checksEl.style.display = '';
      setHtmlIfChanged(checksEl, health.checks.map(function(c) {
        return '<li class="wallet-id__check wallet-id__check--' + (c.ok ? 'ok' : 'bad') + '">' +
          '<span class="wallet-id__check-dot"></span>' + escapeHtml(c.label) + '</li>';
      }).join(''));
    } else if (checksEl) {
      checksEl.style.display = 'none';
      setHtmlIfChanged(checksEl, '');
    }
  }

  // ── HOST CORE — populate the organism mission-control hub ──
  function renderHostCore(snap) {
    const w = snap.worker || {};
    const net = snap.network || {};
    const pool = snap.pool || {};
    const axeFleet = snap.axe_fleet || [];
    const prox = snap.proximity || {};
    const alerts = snap.alerts_recent || [];

    const hcBadge = (id, text) => { const el = document.getElementById(id); if (el) el.textContent = text; };

    hcBadge('hc-hr-badge', fmt.hashrate(w.hashrate));
    hcBadge('hc-net-badge', net.difficulty ? 'diff ' + fmt.diff(net.difficulty) : '—');
    hcBadge('hc-colony-hr', fmt.hashrate(w.hashrate) + ' / ' + fmt.hashrate(net.hashrate));
    hcBadge('hc-best-diff', fmt.diff(w.bestDifficulty));
    hcBadge('hc-network', net.height ? '#' + net.height : '—');

    // Fleet health
    const total = axeFleet.length;
    const online = axeFleet.filter(d => d.status === 'ONLINE').length;
    const healthStr = total > 0 ? (online / total * 100).toFixed(0) + '%' : '—';
    hcBadge('hc-fleet-health', total > 0 ? online + '/' + total + ' (' + healthStr + ')' : '—');

    // Block probability — show ~0% for vanishingly small values
    const pBlock = prox.chance_per_share_pct;
    const pctVal = pBlock != null ? Number(pBlock) * 100 : 0;
    hcBadge('hc-block-prob', pBlock != null ? (pctVal < 0.000001 ? '~0%' : pctVal.toFixed(6) + '%') : '—');

    // Alerts
    hcBadge('hc-alerts', alerts.length > 0 ? alerts.length + ' active' : 'nominal');
  }

  function renderHero(snap) {
    const w = snap.worker || {};
    smoothUpdate(dom.mHashrate, fmt.hashrate(w.hashrate));
    smoothUpdate(dom.mBestDiff, fmt.diff(w.bestDifficulty));
    if (dom.mLastShare) dom.mLastShare.textContent = w.lastSubmission ? fmt.age(w.lastSubmission) : '\u2014';
    if (dom.mState) {
      dom.mState.textContent = w.hashrate ? 'HASHING' : 'IDLE';
      dom.mState.classList.toggle('metric__value--idle', !w.hashrate);
    }
    if (dom.mStateSub) dom.mStateSub.textContent = w.hashrate ? 'active' : 'connected · no shares';
  }


  // ── HOTFIX: Render Raio X miner fleet ──
  function renderMinersXRay(snap) {
    var workers = snap.all_workers || [];
    var section = document.getElementById('raio-x');
    var grid = document.getElementById('raio-x-grid');
    var count = document.getElementById('raio-x-count');
    if (!section || !grid) return;

    if (!workers || workers.length === 0) {
      section.style.display = 'none';
      return;
    }

    section.style.display = 'block';
    var totalHr = 0;
    var online = 0;
    var html = '';
    workers.forEach(function(w) {
      // Field name fallbacks: handle variations from different APIs
      var hr = parseFloat(w.hashrate || w.hashrate1m || w.hashrate1h || w.hr || 0);
      totalHr += hr;
      var isOnline = hr > 0;
      if (isOnline) online++;
      var statusClass = isOnline ? 'raio-x__led--on' : 'raio-x__led--off';
      var statusLabel = isOnline ? 'ONLINE' : 'OFFLINE';
      var hrStr = hr >= 1e12 ? (hr/1e12).toFixed(2) + ' TH/s' : hr >= 1e9 ? (hr/1e9).toFixed(2) + ' GH/s' : hr + ' H/s';
      var rawName = String(w.name || w.worker || w.id || 'unknown');
      var name = decodeHtmlEntities(rawName);
      var shortName = name.length > 20 ? name.slice(0, 18) + '...' : name;
      var best = w.bestDifficulty || w.best_diff || w.bestShare || w.best_share || '';
      var bestStr = best ? String(best) : '';
      var bestShort = bestStr.length > 12 ? bestStr.slice(0, 10) + '...' : bestStr || '—';
      var uptime = w.uptime || w.up_time || w.uptimeSeconds || w.runtime || '—';
      var lastSub = parseInt(w.lastSubmission || w.last_submission || w.last_share || w.lastShare || 0);
      var age = lastSub > 0 ? Math.floor((Date.now()/1000 - lastSub) / 60) + 'm ago' : '—';
      var temp = w.temperature || w.temp || w.temp_pcb || w.temp_chip || null;
      var tempStr = temp !== null ? temp + '°C' : '—';
      var eff = w.efficiency || w.eff || null;
      var effStr = eff !== null ? eff.toFixed(1) + ' J/TH' : '';

      html += '<div class="raio-x__card">';
      html += '<div class="raio-x__header">';
      html += '<span class="raio-x__led ' + statusClass + '"></span>';
      html += '<span class="raio-x__status ' + statusClass + '">' + statusLabel + '</span>';
      html += '<span class="raio-x__name" title="' + name + '">' + shortName + '</span>';
      html += '</div>';
      html += '<div class="raio-x__metrics">';
      html += '<div class="raio-x__metric"><span class="raio-x__m-label">HR</span><span class="raio-x__m-val">' + hrStr + '</span></div>';
      html += '<div class="raio-x__metric"><span class="raio-x__m-label">Best</span><span class="raio-x__m-val">' + bestShort + '</span></div>';
      html += '<div class="raio-x__metric"><span class="raio-x__m-label">Temp</span><span class="raio-x__m-val">' + tempStr + '</span></div>';
      html += '<div class="raio-x__metric"><span class="raio-x__m-label">Last</span><span class="raio-x__m-val">' + age + '</span></div>';
      html += '<div class="raio-x__metric"><span class="raio-x__m-label">Up</span><span class="raio-x__m-val">' + uptime + '</span></div>';
      if (effStr) {
        html += '<div class="raio-x__metric raio-x__metric--wide"><span class="raio-x__m-label">Eff</span><span class="raio-x__m-val">' + effStr + '</span></div>';
      }
      html += '</div></div>';
    });

    grid.innerHTML = html;
    if (count) {
      var totalHrStr = totalHr >= 1e12 ? (totalHr/1e12).toFixed(2) + ' TH/s' : totalHr >= 1e9 ? (totalHr/1e9).toFixed(2) + ' GH/s' : totalHr + ' H/s';
      count.textContent = workers.length + ' miners · ' + online + ' online · ' + totalHrStr;
    }
  }

function renderPool(pool, luck) {
    if (!pool) return;
    // ── FASE 1: Stale data indicator ──
    const isStale = pool._stale === true;
    const panel = document.getElementById('pool-overview');
    if (panel) {
      panel.classList.toggle('is-stale', isStale);
      if (isStale && dom.pStaleBadge) {
        dom.pStaleBadge.textContent = 'STALE (' + (pool._stale_since_ts ? fmt.age(pool._stale_since_ts) : 'old') + ')';
        dom.pStaleBadge.style.display = 'inline';
      } else if (dom.pStaleBadge) {
        dom.pStaleBadge.style.display = 'none';
      }
    }
    if (dom.pHashrate) dom.pHashrate.textContent = fmt.hashrate(pool.hashrate);
    if (dom.pWorkers) dom.pWorkers.textContent = `${pool.workers || 0} / ${pool.users || 0}`;
    if (dom.pHighDiff) dom.pHighDiff.textContent = fmt.diff(pool.highestDiff);
    // FIX: p-last-block — truncate hash to short label + show full hash on hover
    if (dom.pLastBlock) {
      // Use lastBlockTime as block number (API returns height, not timestamp)
      var blockNum = pool.lastBlockTime || 0;
      var refHash = pool.lastBlockHash || '';
      dom.pLastBlock.textContent = blockNum > 0 ? '#' + blockNum.toLocaleString() : '\u2014';
      dom.pLastBlock.title = refHash || '';
    }
    if (dom.pLastBlockTime && pool.lastBlockTime) dom.pLastBlockTime.textContent = fmt.age(pool.lastBlockTime);
    // FIX: p-work-fill — use round_progress_pct from luck_estimate
    if (dom.pWorkFill && luck && luck.round_progress_pct != null) {
      var pct = Math.min(100, Math.max(0, luck.round_progress_pct));
      dom.pWorkFill.style.width = pct + '%';
    }
    // FIX: p-work-num — format workSinceLastBlock
    if (dom.pWorkNum) {
      var w = Number(pool.workSinceLastBlock) || 0;
      dom.pWorkNum.textContent = w > 0 ? fmt.diff(w) + ' work' : '\u2014';
    }
  }

  function renderNetwork(net) {
    if (!net) return;
    if (dom.nHeight) dom.nHeight.textContent = net.height ? `#${net.height}` : '\u2014';
    if (dom.nDiff) dom.nDiff.textContent = fmt.diff(net.difficulty);
    if (dom.nHashrate) dom.nHashrate.textContent = fmt.hashrate(net.hashrate);
    _staleChip(dom.nDiff, net.stale, 'dados em cache');
  }

  // → domínio Automations/Alerts/Auto-Pilot/Decision Matrix extraído para `static/src/41-automations.js` (RFC 478, Issue 540)

  function applyLiveMetrics(live) {
    const patch = liveMetricsPatch(live);
    const hr = document.getElementById('tbar-hr');
    if (hr) hr.textContent = patch.hashrateText;
    const temp = document.getElementById('tbar-temp');
    if (temp) temp.textContent = patch.tempText;
    if (dom.mHashrate) dom.mHashrate.textContent = patch.hashrateText;
    if (dom.hudHashrate) dom.hudHashrate.textContent = patch.hashrateText;
    if (dom.pHashrate) dom.pHashrate.textContent = patch.poolHashrateText;
    renderSnapshotFreshness({ ts: live && live.ts });
  }

  // ── Charts — renderChart fetches data and updates Chart.js instances ──
  const CHART_METRICS = {
    'chart-hashrate': { chart: 'hashrate', label: 'Worker Hashrate', color: 'rgb(6,214,240)' },
    'chart-pool': { chart: 'pool', label: 'Pool Hashrate', color: 'rgb(247,147,26)' },
    'chart-bestdiff': { chart: 'bestdiff', label: 'Best Difficulty', color: 'rgb(16,185,129)' },
    'chart-net': { chart: 'net', label: 'Network Difficulty', color: 'rgb(168,85,247)' },
    'chart-cumulative-p': { chart: 'cum_p', label: 'Cumulative P(Block)', color: 'rgb(168,85,247)' },
    'chart-share-dist': { chart: 'share_dist', label: 'Share Difficulty', color: 'rgb(16,185,129)' },
  };
  // Selected time-range per chart id (default 1h). Persisted so the 15s
  // renderCharts refresh keeps the user's toolbar choice instead of silently
  // resetting every chart back to 1h (audit: range chips were being ignored).
  const _chartRange = {};
  function _fmtChartLabel(t, cfg, id) {
    if (cfg.chart === 'share_dist') return String(t); // histogram bucket labels
    const d = new Date(t);
    const rng = _chartRange[id] || '1h';
    const hm = d.getHours() + ':' + String(d.getMinutes()).padStart(2, '0');
    // Ranges ≥24h span multiple days — include dd/mm so the axis stays honest.
    if (rng === '24h' || rng === '7d' || rng === '30d' || rng === 'all') {
      return String(d.getDate()).padStart(2, '0') + '/' + String(d.getMonth() + 1).padStart(2, '0') + ' ' + hm;
    }
    return hm;
  }
  // The Share-Distribution panel badge was hardcoded to "0 shares" in the HTML
  // and never updated. Reflect the real histogram count from the API.
  function _updateShareDistBadge(cfg, data, values) {
    if (!cfg || cfg.chart !== 'share_dist') return;
    const badge = document.getElementById('share-dist-count-badge');
    if (!badge) return;
    const n = (data && data.count != null) ? data.count : values.reduce((a, b) => a + (Number(b) || 0), 0);
    badge.textContent = `${n} shares`;
  }
  // P0-1: overlay the network target difficulty on the share histogram — a
  // solid purple reference line + readable badge so the operator sees how far
  // shares are from block-winning difficulty at a glance.
  function _applyShareDistTarget(cfg, data, chart) {
    if (!cfg || cfg.chart !== 'share_dist' || !chart) return;
    const bucket = (data && data.target_bucket != null) ? data.target_bucket : null;
    if (bucket != null) {
      chart._annotations = (chart._annotations || []).concat([{ index: bucket, target: true }]);
    }
    const badge = document.getElementById('share-dist-target-badge');
    if (badge) {
      badge.textContent = (data && data.target_diff) ? 'target ' + fmt.diff(data.target_diff) : 'target —';
    }
  }

  async function loadChartData(id) {
    const cfg = CHART_METRICS[id];
    if (!cfg) return;
    try {
      const r = await fetch(`/api/chart-data?chart=${cfg.chart}&range=${_chartRange[id] || '1h'}`);
      if (r.status === 402) { await handleLicenseRequired(r); _chartRange[id] = '1h'; const _tb = document.getElementById('share-dist-target-badge'); if (_tb) _tb.textContent = 'target —'; return; }
      if (!r.ok) return;
      const data = await r.json();
      const chart = charts[id];
      if (!chart) return;
      const rawLabels = (data.labels || []);
      const values = (data.datasets?.[0]?.data || data.datasets?.[0]?.values || []);
      chart.data.labels = rawLabels.map(t => _fmtChartLabel(t, cfg, id));
      chart.data.datasets[0].data = values;
      _updateShareDistBadge(cfg, data, values);
      // Fase 2.1: SMA overlay + shares bar + event annotations
      if (chart.data.datasets[1] && cfg.chart !== 'share_dist') {
        chart.data.datasets[1].data = computeSMA(values, Math.max(3, Math.round(values.length / 10)));
      }
      if (chart.data.datasets[2] && Array.isArray(data.shares)) {
        chart.data.datasets[2].data = data.shares;
        chart.options.scales.y1.display = data.shares.some(s => s > 0);
      }
      chart._annotations = buildChartAnnotations(data.events || [], rawLabels);
      _applyShareDistTarget(cfg, data, chart);
      chart.update('none');
    } catch (e) { /* chart load silently */ }
  }
  // R1: gated chart-data ranges (30d/all) return 402 when the gate is live
  // and no key is present — reset the range to 1h and surface the CTA so the
  // chart never silently renders an empty panel.
  function renderCharts() {
    // Charts can only be measured when their canvases are visible.
    // In module-mode the tab panes are controlled by activateModule();
    // in legacy tab mode they are gated by the .active class.
    var chartsTab = document.getElementById('tab-charts');
    var inModuleMode = document.body.classList.contains('module-mode');
    if (!chartsTab) return;
    if (!inModuleMode && !chartsTab.classList.contains('active')) return;
    Object.keys(CHART_METRICS).forEach(id => {
      const canvas = document.getElementById(id);
      if (!canvas) return;
      // Pula canvases dentro de painéis ocultos (outro módulo) —
      // Chart.js não consegue medir display:none
      if (inModuleMode && canvas.offsetParent === null) return;
      // init chart if not yet created
      if (!charts[id]) {
        const cfg = CHART_METRICS[id];
        charts[id] = makeChart(id, cfg.label, cfg.color);
      }
      loadChartData(id);
    });
  }

  // → domínio Terminal/SSE extraído para `static/src/39-terminal.js` (RFC 478, Issue 529)

  // → domínio Probability/Block Model extraído para `static/src/42-probability.js` (RFC 478, Issue 542)

  // → domínio Automations/Alerts/Auto-Pilot/Decision Matrix extraído para `static/src/41-automations.js` (RFC 478, Issue 540)

  // ── Braiins spot buy modal (real money — explicit confirm only) ───────
  let _braiinsBuyQuote = null;   // last /quote payload
  let _braiinsBuyOrderId = '';   // idempotency key, regenerated per modal session
  let _braiinsBuyBalance = null; // {available_sat,...} or null (unknown/failed)

  function _braiinsBuyModal() { return document.getElementById('braiins-buy-modal'); }

  function _braiinsBuySet(id, v) { const e = document.getElementById(id); if (e) e.textContent = v; }

  function openBraiinsBuyModal(prefill) {
    const modal = _braiinsBuyModal();
    if (!modal) return;
    // Reset the form + status on every open (never carry a stale bid).
    ['braiins-buy-th', 'braiins-buy-amount', 'braiins-buy-stratum',
     'braiins-buy-identity', 'braiins-buy-memo', 'braiins-buy-type'].forEach(id => {
      const e = document.getElementById(id); if (e) e.value = '';
    });
    const ack = document.getElementById('braiins-buy-ack'); if (ack) ack.checked = false;
    _braiinsBuySet('braiins-buy-calc', '—');
    _braiinsBuySet('braiins-buy-status', '');
    // Reset balance display + guard (the quote below re-fills them). Classes
    // are reset too — a previous is-exceeded/is-unknown must not flash red
    // through the 'carregando…' state.
    _braiinsBuyBalance = null;
    _braiinsBuySet('braiins-buy-balance', 'saldo: carregando…');
    _syncBraiinsBalanceClass('loading');
    const submit = document.getElementById('braiins-buy-submit');
    if (submit) submit.disabled = true;
    openModalAnimated(modal);
    _braiinsBuyOrderId = 'c65-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 8);
    // 'comprar agora' prefill: derive TH + budget from the arbitrage signal's
    // CURRENT market price (e.g. 1000 TH/s ≈ 1 PH/s × ~24h at that price), so
    // the user only adds their stratum + typed confirmation. The live quote
    // below still wins for the actual bid price.
    const _prefillPrice = (prefill && prefill.price_sats_per_thh > 0)
      ? prefill.price_sats_per_thh : 0;
    if (_prefillPrice > 0) {
      // TH prefill: explicit override > tenant's typical order size
      // (suggested_th from the arbitrage signal) > 1000 TH default.
      const th = prefill.th || prefill.suggested_th || 1000;
      const amount = Math.max(1000, Math.round(_prefillPrice * th * 24 / 1000) * 1000);
      const thEl = document.getElementById('braiins-buy-th'); if (thEl) thEl.value = th;
      const amtEl = document.getElementById('braiins-buy-amount'); if (amtEl) amtEl.value = amount;
    }
    _braiinsBuyCalc();
    // Load the live ask + tenant balance to prefill the quote line. When the
    // prefill came from an arbitrage signal, show THAT price explicitly so the
    // 'preço atual pré-preenchido' is visible even if the live quote fails
    // (the live ask overwrites this line on success).
    _braiinsBuySet('braiins-buy-quote', _prefillPrice > 0
      ? '⚡ pré-preenchido do sinal: ' + _prefillPrice + ' sats/TH·h · carregando cotação live…'
      : 'carregando cotação…');
    _renderBraiinsBuyUnit();
    fetch('/api/rentals/braiins/quote')
      .then(r => r.ok ? r.json() : null)
      .then(q => {
        _braiinsBuyQuote = q;
        if (!q || !q.available) {
          _braiinsBuySet('braiins-buy-quote', '⚠ ' + ((q && q.error) || 'cotação indisponível'));
          // Balance stays unknown — surface the is-unknown state (this branch
          // previously returned before _renderBraiinsBuyBalance, leaving the
          // line stuck on 'carregando…' forever).
          _renderBraiinsBuyBalance();
          return;
        }
        const bal = q.balance || {};
        const balTxt = bal.available ? (bal.available_sat != null ? Number(bal.available_sat).toLocaleString('en-US') + ' sats disponíveis' : 'saldo: verifique na conta') : ((bal.error || '') ? 'saldo indisponível (' + bal.error + ')' : '—');
        _braiinsBuySet('braiins-buy-quote',
          'ASK MENOR: ' + q.price_sats_per_thh + ' sats/TH·h · ' + q.price_sat_per_ph_day + ' sats/PH·dia · ' + balTxt);
        // Balance guard: keep the raw number so _braiinsBuyCalc can BLOCK the
        // submit when the budget exceeds the available sats.
        _braiinsBuyBalance = bal.available && bal.available_sat != null
          ? bal : null;
        _renderBraiinsBuyBalance();
        _braiinsBuyCalc();
      })
      .catch(() => _braiinsBuySet('braiins-buy-quote', '⚠ falha ao carregar cotação'));
  }

  function _syncBraiinsBalanceClass(state) {
    // Single source of truth for the balance-line state classes — called
    // from every path (open / quote ok / quote fail / calc) so the visual
    // state can never drift from the actual guard.
    //   state: 'loading' | 'known' | 'exceeded' | 'unknown'
    const el = document.getElementById('braiins-buy-balance');
    if (!el) return;
    el.classList.remove('is-known', 'is-exceeded', 'is-unknown');
    if (state === 'known') el.classList.add('is-known');
    else if (state === 'exceeded') el.classList.add('is-exceeded');
    else if (state === 'unknown') el.classList.add('is-unknown');
  }

  function _renderBraiinsBuyBalance() {
    const bal = _braiinsBuyBalance;
    if (bal) {
      const sat = Number(bal.available_sat) || 0;
      _braiinsBuySet('braiins-buy-balance', 'SALDO DISPONÍVEL: ' + sat.toLocaleString('en-US') + ' sats');
      _syncBraiinsBalanceClass('known');
      _braiinsBuyCalc();  // re-evaluate the guard when balance arrives
    } else {
      _braiinsBuySet('braiins-buy-balance', 'saldo: indisponível — verifique sua chave Braiins no Settings');
      _syncBraiinsBalanceClass('unknown');
    }
  }

  function _renderBraiinsBuyUnit() {
    // Live pricing unit + F7 bid cap (GET /api/rentals/braiins/market) — shows
    // the account's unit next to the quote and the active-bid count against
    // max_bids_per_subaccount (N/M), so a non-PH/day account AND a cap
    // situation are visible before any money moves. Never blocks the modal:
    // on failure the chip stays '—' (the 400 fail-closed in
    // create_braiins_bid is the guard).
    const el = document.getElementById('braiins-buy-unit');
    if (!el) return;
    _braiinsBuySet('braiins-buy-unit', 'unit: —');  // reset on every open — never carry a stale unit
    el.classList.remove('is-active', 'is-danger');
    fetch('/api/rentals/braiins/market')
      .then(r => (r.ok ? r.json() : null))
      .then(m => {
        const hr = m && m.market && m.market.hr_unit;
        if (!hr) return;
        const maxBids = m.market.max_bids_per_subaccount;
        const active = m.active_bids_count;
        let txt = 'unit: ' + hr;
        if (maxBids != null) {
          txt += ' · bids ' + (active != null ? active : '?') + '/' + maxBids;
        }
        el.textContent = txt;
        el.classList.add('is-active');
        // At the cap: the submit would 400 (F7) — surface it in red.
        if (maxBids != null && active != null && active >= maxBids) {
          el.classList.add('is-danger');
        }
      })
      .catch(() => {});
  }

  function _braiinsBuyCalc() {
    const th = parseFloat(document.getElementById('braiins-buy-th')?.value) || 0;
    const amount = parseInt(document.getElementById('braiins-buy-amount')?.value, 10) || 0;
    const q = _braiinsBuyQuote;
    let out = '—';
    if (q && q.available && th > 0) {
      const ph = th / 1000;
      // At the cheapest ask, how long does the budget last (TH·h / TH = h)?
      const thh = amount > 0 && q.price_sats_per_thh > 0 ? amount / q.price_sats_per_thh : 0;
      const hours = thh > 0 && th > 0 ? thh / th : 0;
      out = th.toLocaleString('en-US') + ' TH/s = ' + ph.toLocaleString('en-US', { maximumFractionDigits: 3 }) + ' PH/s';
      if (amount > 0 && hours > 0) {
        out += ' · budget cobre ~' + (hours >= 1 ? Math.round(hours) + 'h' : Math.round(hours * 60) + 'min') + ' de hashrate';
      }
    }
    // Balance guard: budget > available sats → warn + keep submit BLOCKED.
    const bal = _braiinsBuyBalance;
    const balSat = bal ? (Number(bal.available_sat) || 0) : null;
    const exceeded = balSat != null && amount > balSat;
    if (exceeded) {
      out += ' · ⚠ budget EXCEDE o saldo em ' + (amount - balSat).toLocaleString('en-US') + ' sats';
      // Sync BOTH ways: when the user lowers the budget back under the
      // balance the class must clear, not linger red forever.
      _syncBraiinsBalanceClass('exceeded');
    } else if (balSat != null) {
      _syncBraiinsBalanceClass('known');
    }
    _braiinsBuySet('braiins-buy-calc', out);
    // Enable only when: live quote present, hashrate > 0, budget + stratum
    // present, budget ≤ available balance, ack checked, typed COMPRAR. A
    // missing quote (network down / no ask) BLOCKS the order — never bid
    // blind with real money.
    const quoteOk = !!(q && q.available);
    const typed = (document.getElementById('braiins-buy-type')?.value || '').trim().toUpperCase() === 'COMPRAR';
    const ack = document.getElementById('braiins-buy-ack')?.checked || false;
    const stratum = (document.getElementById('braiins-buy-stratum')?.value || '').trim();
    const identity = (document.getElementById('braiins-buy-identity')?.value || '').trim();
    const submit = document.getElementById('braiins-buy-submit');
    if (submit) submit.disabled = !(quoteOk && th > 0 && amount >= 1000 && !exceeded && stratum && identity && typed && ack);
    // F4 hint: worker identity is REQUIRED (Braiins contract) — never leave
    // the operator guessing why the button is dead. Set when missing, and
    // CLEAR the hint once filled (stale-hint bug: the status must not keep
    // saying "informe a worker identity" after the field is filled).
    if (!identity && th > 0 && stratum) {
      const cur = document.getElementById('braiins-buy-status')?.textContent || '';
      if (!cur) _braiinsBuySet('braiins-buy-status', 'informe a worker identity (user.worker) para liberar a compra');
    } else if (identity) {
      const cur = document.getElementById('braiins-buy-status')?.textContent || '';
      if (cur.includes('worker identity')) _braiinsBuySet('braiins-buy-status', '');
    }
  }

  async function submitBraiinsBid() {
    const submit = document.getElementById('braiins-buy-submit');
    setBtnLoading(submit, true);
    _braiinsBuySet('braiins-buy-status', 'enviando ordem…');
    try {
      const th = parseFloat(document.getElementById('braiins-buy-th')?.value) || 0;
      const amount = parseInt(document.getElementById('braiins-buy-amount')?.value, 10) || 0;
      const body = {
        speed_limit_th: th,
        amount_sat: amount,
        price_sat: (_braiinsBuyQuote && _braiinsBuyQuote.price_sat_per_ph_day) || 0,
        upstream_url: (document.getElementById('braiins-buy-stratum')?.value || '').trim(),
        upstream_identity: (document.getElementById('braiins-buy-identity')?.value || '').trim(),
        memo: (document.getElementById('braiins-buy-memo')?.value || '').trim(),
        cl_order_id: _braiinsBuyOrderId,
      };
      // Server-side two-phase safety: validate a read-only preview first, then
      // bind the one-time confirmation token to this exact payload. The same
      // client order id is also the persistent idempotency key.
      _braiinsBuySet('braiins-buy-status', 'validando ordem (dry-run)…');
      const previewResponse = await authFetch('/api/rentals/braiins/bid', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...body, dry_run: true }),
      });
      const preview = await previewResponse.json().catch(() => ({}));
      if (!previewResponse.ok || !preview.success || !preview.confirmation_token) {
        _braiinsBuySet('braiins-buy-status', '⚠ ' + (preview.error || 'dry-run rejeitado'));
        setBtnLoading(submit, false);
        return;
      }
      _braiinsBuySet('braiins-buy-status', 'dry-run aprovado · enviando uma única ordem…');
      const r = await authFetch('/api/rentals/braiins/bid', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Idempotency-Key': _braiinsBuyOrderId,
        },
        body: JSON.stringify({
          ...body,
          dry_run: false,
          confirmation_token: preview.confirmation_token,
        }),
      });
      const data = await r.json().catch(() => ({}));
      if (r.ok && data.success) {
        setBtnLoading(submit, false);
        _braiinsBuySet('braiins-buy-status', '✅ ordem enviada — id ' + (data.bid && data.bid.id ? data.bid.id : 'confirmada na Braiins'));
        // Conversion telemetry is recorded SERVER-SIDE on bid success
        // (single source of truth — no double counting).
      } else if (data.state === 'unknown' || data.reconciliation?.state === 'unknown') {
        _braiinsBuySet('braiins-buy-status', '⚠ resultado desconhecido — NÃO tente novamente; reconcilie com a Braiins');
        setBtnLoading(submit, false);
      } else {
        _braiinsBuySet('braiins-buy-status', '⚠ ' + (data.error || 'falha ao enviar ordem'));
        setBtnLoading(submit, false);
      }
    } catch (e) {
      _braiinsBuySet('braiins-buy-status', '⚠ erro de rede ao enviar ordem');
      setBtnLoading(submit, false);
    }
  }

  function _initBraiinsBuyModal() {
    const modal = _braiinsBuyModal();
    if (!modal) return;
    modal.addEventListener('click', (e) => {
      if (e.target.matches('[data-close]') || e.target === modal) closeModalAnimated(modal);
    });
    ['braiins-buy-th', 'braiins-buy-amount', 'braiins-buy-stratum', 'braiins-buy-identity', 'braiins-buy-type']
      .forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('input', _braiinsBuyCalc);
      });
    const ack = document.getElementById('braiins-buy-ack');
    if (ack) ack.addEventListener('change', _braiinsBuyCalc);
    const submit = document.getElementById('braiins-buy-submit');
    if (submit) submit.addEventListener('click', submitBraiinsBid);
  }
  _initBraiinsBuyModal();

  // ── AI Operator render ──
  let _aiInited = false;
  function renderAiOperator(snap) {
    if (!_aiInited) {
      _aiInited = true;
      _initAiChat();
    }

    // Update context sidebar
    const w = snap.worker || {};
    const net = snap.network || {};
    const fleet = snap.axe_fleet || [];
    const prox = snap.proximity || {};

    document.getElementById('ai-ctx-status') && (document.getElementById('ai-ctx-status').textContent = snap.worker ? (snap.worker.hashrate ? 'ONLINE' : 'IDLE') : 'OFFLINE');
    document.getElementById('ai-ctx-hr') && (document.getElementById('ai-ctx-hr').textContent = fmt.hashrate(w.hashrate));
    document.getElementById('ai-ctx-best') && (document.getElementById('ai-ctx-best').textContent = fmt.diff(w.bestDifficulty));
    document.getElementById('ai-ctx-net') && (document.getElementById('ai-ctx-net').textContent = fmt.diff(net.difficulty));
    // Real-user audit: Net HR / Height / Price were never populated — the
    // CONTEXT sidebar showed "—" for three of nine rows forever. Same
    // sources the status bar uses (network.hashrate, network.height,
    // btc_price.usd).
    document.getElementById('ai-ctx-nethr') && (document.getElementById('ai-ctx-nethr').textContent = fmt.hashrate(net.hashrate));
    document.getElementById('ai-ctx-net-height') && (document.getElementById('ai-ctx-net-height').textContent = net.height ? '#' + net.height : '—');
    const btcUsdCtx = (snap.btc_price && snap.btc_price.usd) || (net.btc_usd) || null;
    document.getElementById('ai-ctx-price') && (document.getElementById('ai-ctx-price').textContent = btcUsdCtx ? '$' + Number(btcUsdCtx).toLocaleString() : '—');
    document.getElementById('ai-ctx-fleet') && (document.getElementById('ai-ctx-fleet').textContent = fleet.length + ' devices');
    document.getElementById('ai-ctx-pblock') && (document.getElementById('ai-ctx-pblock').textContent = prox.chance_per_share_pct ? (Number(prox.chance_per_share_pct) * 100).toFixed(6) + '%' : '—');

    // ── Auto-Pilot armed state (server truth from snapshot) → toggle UI ──
    const ap = snap.auto_pilot || {};
    _apSetUi(!!ap.armed);
    _initAutoPilotToggle();
    _initAutoPilotAutoToggle();
    _initAutoPilotAdvisory();
    _initAutoPilotDryRun();
  }

  // → domínio Automations/Alerts/Auto-Pilot/Decision Matrix extraído para `static/src/41-automations.js` (RFC 478, Issue 540)

  function _initAiChat() {
    const input = document.getElementById('ai-input');
    const send = document.getElementById('ai-send');
    const clear = document.getElementById('ai-clear');
    const messages = document.getElementById('ai-messages');
    if (!input || !send || !messages) return;

    const responses = {
      'hashrate': 'Current hashrate is **{hr}**. This is the speed at which your miners are computing SHA-256 hashes. To improve: add more ASICs, optimize your fleet, or rent hashpower from the market.',
      'temperature': 'Monitoring fleet temperature is critical. Keep ASICs below 75°C for optimal lifespan. Check the Axe Fleet panel for per-device telemetry.',
      'probability': 'Block finding probability depends on your hashrate vs the network difficulty. Currently {pblock}. With solo mining, each share is an independent lottery ticket.',
      'difficulty': 'Network difficulty adjusts every 2016 blocks. Your best difficulty is historical context only; it is not progress toward a block.',
      'best diff': 'Best difficulty is the highest observed share difficulty. It is historical context, not progress, and does not change the next-hash odds.',
      'market': 'Hashrate market data shows rental prices from various providers. Compare costs and expected value before renting hashpower.',
      'fleet': 'Your fleet dashboard shows {fleet} devices. Each device reports hashrate, temperature, power draw, and shares. Monitor for anomalies.',
      'profitability': 'Scenario economics uses the current hashrate, difficulty, configured costs and BTC price. It is a constant-input estimate, not a profit promise.',
      'hello': 'I\'m CYPHER AI, your mining operations intelligence. Ask me about your fleet, probability calculations, market opportunities, or mining metrics.',
    };

    function addMessage(role, content) {
      const div = document.createElement('div');
      div.className = 'ai-msg ai-msg--' + role;
      div.innerHTML = '<div class="ai-msg__header">' + (role === 'user' ? 'You' : '◆ CYPHER AI') + '</div><div class="ai-msg__content">' + content + '</div>';
      messages.appendChild(div);
      messages.scrollTop = messages.scrollHeight;
    }

    function findBestResponse(query) {
      const q = query.toLowerCase();
      const keys = Object.keys(responses);
      let bestKey = 'default';
      let bestScore = 0;
      for (const k of keys) {
        let score = 0;
        const words = k.split(' ');
        for (const w of words) { if (q.includes(w)) score += 10; }
        for (const w of q.split(' ')) { if (k.includes(w) && w.length > 2) score += 5; }
        if (score > bestScore) { bestScore = score; bestKey = k; }
      }
      if (bestScore < 5) return null;
      return bestKey;
    }

    function getResponse(query) {
      const key = findBestResponse(query);
      if (!key) {
        return 'I\'m not sure about that. Try asking about: hashrate, probability, difficulty, market, fleet, profitability, or temperature.';
      }
      let resp = responses[key] || 'Processing your query...';
      // Fill in dynamic context
      const hr = document.getElementById('ai-ctx-hr')?.textContent || '—';
      const pblock = document.getElementById('ai-ctx-pblock')?.textContent || '—';
      const fleetCt = document.getElementById('ai-ctx-fleet')?.textContent || '—';
      resp = resp.replace('{hr}', hr).replace('{pblock}', pblock).replace('{fleet}', fleetCt);
      return resp;
    }

    // PREMIUM (Issue #182): o AI real (LLM via SSE) é o recurso premium.
    // Entitled quando open mode (tudo grátis) OU tier PREMIUM — e o servidor
    // tem chave de LLM configurada (ai_configured). Senão, bot local.
    function aiCanUseReal() {
      return !!(_license.ai_configured && (_license.mode === 'open' || _license.premium));
    }

    function showPremiumCta(d) {
      logMessage('PREMIUM', (d && d.error) || 'AI Operator real é PREMIUM — upgrade necessário', 'WARN');
      openUpgradeModal();
    }

    // Streams /api/ai/query (SSE). On success morphs typingDiv into the real
    // answer; returns true when a real response was shown (text or a handled
    // provider error). False → caller falls back to the local bot.
    async function tryRealAi(text, typingDiv) {
      // Timeout: um LLM pendurado não pode deixar o indicador de typing
      // para sempre — aborta após 45s e o caller cai no bot local.
      const ctrl = (typeof AbortController !== 'undefined') ? new AbortController() : null;
      const timer = ctrl ? setTimeout(function () { try { ctrl.abort(); } catch (e) {} }, 45000) : null;
      try {
        const r = await authFetch('/api/ai/query', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ query: text }),
          signal: ctrl ? ctrl.signal : undefined,
        });
        if (!r.ok) {
          if (r.status === 402) {
            const d = await r.json().catch(() => ({}));
            if (d && d.required_tier === 'premium') showPremiumCta(d);
          }
          return false;
        }
        if (!r.body || !r.body.getReader) return false;
        const reader = r.body.getReader();
        const decoder = new TextDecoder();
        let buf = '';
        let acc = '';
        let sawText = false;
        let sawError = false;
        const contentEl = document.createElement('div');
        contentEl.className = 'ai-msg__content';
        typingDiv.innerHTML = '<div class="ai-msg__header">◆ CYPHER AI</div>';
        typingDiv.appendChild(contentEl);
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          buf += decoder.decode(value, { stream: true });
          let idx;
          while ((idx = buf.indexOf('\n\n')) !== -1) {
            const raw = buf.slice(0, idx).trim();
            buf = buf.slice(idx + 2);
            if (!raw.startsWith('data:')) continue;
            let obj = {};
            try { obj = JSON.parse(raw.slice(5).trim()); } catch (e) { continue; }
            if (obj.type === 'text') {
              sawText = true;
              acc += obj.content || '';
              contentEl.textContent = acc;
              messages.scrollTop = messages.scrollHeight;
            } else if (obj.type === 'error') {
              sawError = true;
              contentEl.textContent = obj.message || 'AI error';
            } else if (obj.type === 'done') {
              break;
            }
          }
        }
        if (!sawText && !sawError) return false;
        return true;
      } catch (e) {
        return false;  // aborted (timeout), rede ou 5xx → fallback pro bot local
      } finally {
        if (timer) clearTimeout(timer);
      }
    }

    async function handleSend() {
      try {
        const text = input.value.trim();
        if (!text) return;
        input.value = '';
        send.disabled = true;

        addMessage('user', escapeHtml(text));

        // Show typing indicator
        const typingDiv = document.createElement('div');
        typingDiv.className = 'ai-msg ai-msg--assistant';
        typingDiv.innerHTML = '<div class="ai-msg__header">◆ CYPHER AI</div><div class="ai-typing"><span class="ai-typing__dot"></span><span class="ai-typing__dot"></span><span class="ai-typing__dot"></span></div>';
        messages.appendChild(typingDiv);
        messages.scrollTop = messages.scrollHeight;

        // Real AI (PREMIUM/open mode) ou bot local — nunca quebra o chat.
        let usedReal = false;
        if (aiCanUseReal()) {
          usedReal = await tryRealAi(text, typingDiv);
        }
        if (!usedReal) {
          // Brief processing delay (bot local)
          await new Promise(r => setTimeout(r, 200 + Math.random() * 300));
          typingDiv.remove();
          const response = getResponse(text);
          const formatted = response.replace(/\*\*(.*?)\*\*/g, '<strong style="color:var(--accent-btc)">$1</strong>');
          addMessage('assistant', formatted);
        }
      } finally {
        send.disabled = false;
      }
    }

    send.addEventListener('click', handleSend);
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend(); } });
    clear.addEventListener('click', () => {
      messages.innerHTML = '';
      addMessage('assistant', 'Chat cleared. Ask me anything about your mining operation.');
    });
  }

  // ── Main render ──
  let prevSnapshot = null;
  function render(snap) {
    if (!_skeletonsHidden) hideSkeletons();
    // Sync window.BTC_ADDRESS from snapshot so modal and other components stay consistent
    window.BTC_ADDRESS = snap.btc_address || window.BTC_ADDRESS || '';
    toggleWalletCTA();
    renderHUD(snap);
    renderStatusBar(snap);
    renderSnapshotFreshness(snap);
    renderOperationalOverview(snap, _operationalFleetData, _operationalFleetError);
    // P0-4 fix: an empty shortAddr('') collapses the topbar span to a
    // zero-width box (Playwright/flex reports it hidden on wallet-less
    // boots). Keep the '—' placeholder (same convention as #sb-wallet-addr)
    // so the element always has a real box.
    if (dom.topbarAddress) dom.topbarAddress.textContent = `${fmt.shortAddr(snap.btc_address || window.BTC_ADDRESS || '') || '—'}`;
    if (dom.statusText) {
      dom.statusText.textContent = snap.worker ? (snap.worker.hashrate ? 'ONLINE' : 'IDLE') : 'OFFLINE';
    }
    if (dom.statusPill) {
      dom.statusPill.classList.toggle('is-online', !!(snap.worker && snap.worker.hashrate));
      dom.statusPill.classList.toggle('is-idle', !!(snap.worker && !snap.worker.hashrate));
    }
    renderHero(snap);
    renderHostCore(snap);
    renderPool(snap.pool, snap.luck_estimate);
    renderMinersXRay(snap);
    renderNetwork(snap.network);
    renderAccount(snap.account);
    renderBtcPrices(snap.btc_price);
    renderHalving(snap.halving);
    renderMempoolFees(snap.mempool_fees);
    renderProfitability(snap.profitability);
    renderDecisionMatrix(snap.profitability);
    renderComparison(snap);
    renderSoloStats(snap.proximity);
    renderProximity(snap.proximity);
    renderQuantumLock(snap.proximity);
    renderLiveCalc(snap.proximity);
    renderNetworkGauge(snap);
    renderMilestones(snap.milestones);
    renderAlerts(snap.alerts_recent);
    renderEvents(snap.highest_diffs);
    resetLeaderboardFromSnapshot(snap);
    applyLiveMetrics(liveMetricsFromSnapshot(snap));
    if (typeof updateSidebarStatus === 'function') {
      updateSidebarStatus(!!snap.worker);
    }
    renderTimelineFeed(snap.timeline_recent || snap.timeline_last_n);
    renderTerminalEvents(snap.timeline_last_n || snap.timeline_recent);
    renderTimelineStats(snap);
    renderBlockHunt(snap);
    renderCommandCenter(snap);
    renderMarket(snap);
    renderAiOperator(snap);
    renderFleetCommandCenter(snap);
    renderWalletIdentity(snap);
    _lmSetConn(snap);
    renderCharts();
    prevSnapshot = snap;
  }

  // ══════════════════════════════════════════════════════════════════════
  // CHARTS
  // ══════════════════════════════════════════════════════════════════════
  const charts = {};
  // ══════════════════════════════════════════════════════════════════════
  //  FASE 2.1 — PROFESSIONAL CHARTS
  //  moving averages · bar+line overlays · zoom/pan · event annotations
  //  Pure helpers below are mirrored in tests/test_app_js_core.js.
  // ══════════════════════════════════════════════════════════════════════

  // Simple moving average (window in points). Mirrors numpy-rolling mean so
  // the SMA line starts at the first point (partial window at the head).
  function computeSMA(values, windowSize) {
    if (!Array.isArray(values) || !values.length) return [];
    windowSize = Math.max(1, Math.floor(Number(windowSize) || 7));
    const out = [];
    let sum = 0;
    for (let i = 0; i < values.length; i++) {
      sum += Number(values[i]) || 0;
      if (i >= windowSize) sum -= Number(values[i - windowSize]) || 0;
      const n = Math.min(i + 1, windowSize);
      out.push(Number((sum / n).toFixed(2)));
    }
    return out;
  }

  // Map persisted timeline events (ts in seconds) to the nearest label index
  // so the annotation plugin can draw vertical lines at the right x position
  // (category axis — no time adapter needed, stays offline-friendly).
  function buildChartAnnotations(events, labels) {
    if (!Array.isArray(events) || !Array.isArray(labels) || !labels.length) return [];
    const out = [];
    events.forEach(ev => {
      const ts = Number(ev.ts || 0) * 1000;
      if (!ts) return;
      let idx = 0, best = Infinity;
      for (let i = 0; i < labels.length; i++) {
        const d = Math.abs(Number(labels[i]) - ts);
        if (d < best) { best = d; idx = i; }
      }
      out.push({
        index: idx,
        severity: ev.severity || 'INFO',
        message: String(ev.message || ev.event_type || ''),
      });
    });
    return out;
  }

  // ── Zero-dependency annotation plugin (inline, per-chart) ───────────
  // Draws subtle vertical dashed lines at event positions. Bumps/alerts are
  // critical (red), share finds are neutral (amber). Driven by
  // chart._annotations = buildChartAnnotations(...) set on each load.
  const chartEventAnnotationsPlugin = {
    id: 'cypher65EventAnnotations',
    afterDraw(chart) {
      const anns = chart._annotations || [];
      if (!anns.length) return;
      const xScale = chart.scales.x;
      const area = chart.chartArea;
      if (!xScale || !area) return;
      const ctx = chart.ctx;
      ctx.save();
      anns.forEach(a => {
        const x = xScale.getPixelForValue(a.index);
        if (x < area.left || x > area.right) return;
        // P0-1: network target difficulty reference line (solid purple).
        if (a.target) {
          ctx.strokeStyle = 'rgba(168,85,247,0.9)';
          ctx.lineWidth = 1.5;
          ctx.setLineDash([]);
          ctx.beginPath(); ctx.moveTo(x, area.top); ctx.lineTo(x, area.bottom); ctx.stroke();
          return;
        }
        const critical = a.severity === 'CRIT' || a.severity === 'GOLD';
        ctx.strokeStyle = critical ? 'rgba(255,94,94,0.55)' : 'rgba(255,196,0,0.30)';
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 3]);
        ctx.beginPath(); ctx.moveTo(x, area.top); ctx.lineTo(x, area.bottom); ctx.stroke();
        ctx.setLineDash([]);
      });
      ctx.restore();
    },
  };

  // Pure zoom-range clamp for the category axis (x min/max are POINT INDICES,
  // not timestamps). Expressed in point counts so it works on any dataset size.
  // Mirrored in tests/test_app_js_core.js.
  function clampZoomRange(currentRange, factor, minPoints, maxPoints) {
    const next = currentRange * factor;
    const upper = Math.max(minPoints, maxPoints);
    return Math.max(minPoints, Math.min(next, upper));
  }

  // ── Lightweight zoom/pan (wheel zoom + drag pan + dblclick reset) ───
  // Implemented against Chart.js scale min/max directly — no CDN plugin, so
  // the self-hosted dashboard keeps working fully offline.
  // IMPORTANT: the x scale is CATEGORY (labels are HH:mm strings), so min/max
  // are point indices — zoom bounds are clamped in POINT COUNTS (min 5 points,
  // max = full label count), never wall-clock ms.
  // Drag uses Pointer Capture bound to the canvas only — no window listeners,
  // so re-initializing charts can never leak handlers.
  function _attachChartZoom(chart) {
    const canvas = chart.canvas;
    if (!canvas) return;
    const MIN_POINTS = 5;
    const maxPoints = () => Math.max(MIN_POINTS, (chart.data.labels || []).length);
    const resetZoom = () => {
      delete chart.options.scales.x.min;
      delete chart.options.scales.x.max;
      chart.update('none');
    };
    canvas.addEventListener('wheel', e => {
      e.preventDefault();
      const xs = chart.scales.x;
      if (!xs) return;
      const range = xs.max - xs.min;
      if (!range) return;
      const cursor = (e.offsetX / canvas.clientWidth);
      const anchor = xs.min + range * cursor;
      const factor = e.deltaY > 0 ? 1.2 : 0.8333;
      const newRange = clampZoomRange(range, factor, MIN_POINTS, maxPoints());
      const newMin = anchor - newRange * cursor;
      chart.options.scales.x.min = newMin;
      chart.options.scales.x.max = newMin + newRange;
      chart.update('none');
    }, { passive: false });
    let drag = null;
    canvas.addEventListener('pointerdown', e => {
      if (e.button !== 0) return;
      const xs = chart.scales.x;
      if (!xs) return;
      drag = { startX: e.clientX, startMin: xs.min };
      try { canvas.setPointerCapture(e.pointerId); } catch (err) { /* ignore */ }
      canvas.style.cursor = 'grabbing';
    });
    canvas.addEventListener('pointermove', e => {
      if (!drag) return;
      const xs = chart.scales.x;
      if (!xs || !(xs.max - xs.min)) return;
      const dx = (e.clientX - drag.startX) / canvas.clientWidth * (xs.max - xs.min);
      const newMin = drag.startMin - dx;
      chart.options.scales.x.min = newMin;
      chart.options.scales.x.max = newMin + (xs.max - xs.min);
      chart.update('none');
    });
    canvas.addEventListener('pointerup', () => {
      drag = null;
      canvas.style.cursor = '';
    });
    canvas.addEventListener('pointercancel', () => {
      drag = null;
      canvas.style.cursor = '';
    });
    canvas.addEventListener('dblclick', resetZoom);
    canvas.title = 'scroll to zoom · drag to pan · double-click to reset';
  }

  function makeChart(id, label, color) {
    const canvas = document.getElementById(id);
    if (!canvas) return null;
    // Issue #186: defensivo — app.js roda com defer após o Chart.js, mas se o
    // CDN falhar (offline/blocked) o boot não pode crashar. Null é tratado
    // pelos call sites (mesma convenção do canvas ausente).
    if (typeof Chart === 'undefined') return null;
    const ctx = canvas.getContext('2d');
    const cfg = CHART_METRICS[id];
    // Human-readable Y ticks: hashrate/pool render fmt.hashrate (TH/s), best
    // diff/net render fmt.diff — raw 4.7e12 / 1.26e14 labels were unreadable.
    const isHrAxis = cfg && (cfg.chart === 'hashrate' || cfg.chart === 'pool');
    const isDiffAxis = cfg && (cfg.chart === 'bestdiff' || cfg.chart === 'net');
    const yTickCb = isHrAxis ? (v) => fmt.hashrate(v) : isDiffAxis ? (v) => fmt.diff(v) : undefined;
    // P0-5 audit: the share-difficulty histogram was rendered as a line chart
    // with pointRadius 0 + fill alpha 0.1 — with a handful of shares the
    // series was effectively invisible ("empty graph" despite 13+ shares).
    // Histograms belong on bars: one visible column per difficulty bucket.
    const isHistogram = cfg && cfg.chart === 'share_dist';
    const datasets = [
      isHistogram
        ? { label, data: [], borderColor: color, backgroundColor: color.replace(')', ',0.55)').replace('rgb','rgba'), borderWidth: 1, maxBarThickness: 34 }
        : { label, data: [], borderColor: color, backgroundColor: color.replace(')', ',0.1)').replace('rgb','rgba'), fill: true, tension: 0.4, pointRadius: 0 },
    ];
    // Fase 2.1: moving-average overlay (dashed, no fill) on time series
    if (!isHistogram) {
      datasets.push({ label: label + ' · SMA', data: [], borderColor: 'rgba(234,234,235,0.55)', backgroundColor: 'transparent', borderDash: [5, 3], fill: false, tension: 0.4, pointRadius: 0, borderWidth: 1.5 });
    }
    // Fase 2.1: share-volume bar overlay (2nd y-axis, right) on hashrate
    if (cfg && cfg.chart === 'hashrate') {
      datasets.push({ type: 'bar', label: 'Shares/min', data: [], yAxisID: 'y1', backgroundColor: 'rgba(6,214,240,0.14)', borderColor: 'rgba(6,214,240,0.35)', borderWidth: 1, order: 3 });
    }
    const chart = new Chart(ctx, {
      type: isHistogram ? 'bar' : 'line',
      data: { labels: [], datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { ticks: { color: cssVar('--text-tertiary'), maxTicksLimit: 8, font: { family: 'JetBrains Mono, monospace', size: 10 } }, grid: { color: 'rgba(94,89,82,0.14)' } },
          y: { ticks: { color: cssVar('--text-tertiary'), font: { family: 'JetBrains Mono, monospace', size: 10 }, ...(yTickCb ? { callback: yTickCb } : {}) }, grid: { color: 'rgba(94,89,82,0.14)' } },
          y1: { position: 'right', display: false, grid: { drawOnChartArea: false }, ticks: { color: cssVar('--brand'), font: { family: 'JetBrains Mono, monospace', size: 10 } } },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            backgroundColor: 'rgba(17,18,20,0.94)',
            borderColor: 'rgba(255,255,255,0.08)',
            borderWidth: 1,
            titleColor: cssVar('--text-primary'),
            bodyColor: cssVar('--text-secondary'),
            padding: 10,
            boxPadding: 4,
            usePointStyle: true,
            font: { family: 'JetBrains Mono, monospace', size: 11 },
          },
        },
      },
      plugins: [chartEventAnnotationsPlugin],
    });
    if (!isHistogram) _attachChartZoom(chart);
    return chart;
  }

  async function loadChart(id, metric, range) {
    try {
      _chartRange[id] = range || '1h'; // persist the toolbar choice across refreshes
      const r = await fetch(`/api/chart-data?chart=${metric}&range=${range}`);
      if (r.status === 402) { await handleLicenseRequired(r); _chartRange[id] = '1h'; const _tb = document.getElementById('share-dist-target-badge'); if (_tb) _tb.textContent = 'target —'; return; }
      if (!r.ok) return;
      const data = await r.json();
      const chart = charts[id];
      if (!chart) return;
      const cfg = CHART_METRICS[id] || {};
      const rawLabels = (data.labels || []);
      const values = (data.datasets?.[0]?.data || data.datasets?.[0]?.values || []);
      chart.data.labels = rawLabels.map(t => _fmtChartLabel(t, cfg, id));
      chart.data.datasets[0].data = values;
      _updateShareDistBadge(cfg, data, values);
      // Fase 2.1: SMA overlay + shares bar + event annotations
      if (chart.data.datasets[1] && cfg.chart !== 'share_dist') {
        chart.data.datasets[1].data = computeSMA(values, Math.max(3, Math.round(values.length / 10)));
      }
      if (chart.data.datasets[2] && Array.isArray(data.shares)) {
        chart.data.datasets[2].data = data.shares;
        chart.options.scales.y1.display = data.shares.some(s => s > 0);
      }
      chart._annotations = buildChartAnnotations(data.events || [], rawLabels);
      _applyShareDistTarget(cfg, data, chart);
      chart.update('none');
    } catch (e) { /* chart load silently */ }
  }

  function initCharts() {
    charts['chart-hashrate'] = makeChart('chart-hashrate', 'Hashrate', 'rgb(247,147,26)');
    charts['chart-pool'] = makeChart('chart-pool', 'Pool HR', 'rgb(6,214,240)');
    charts['chart-bestdiff'] = makeChart('chart-bestdiff', 'Best Diff', 'rgb(16,185,129)');
    charts['chart-net'] = makeChart('chart-net', 'Net Diff', 'rgb(139,92,246)');
    charts['chart-cumulative-p'] = makeChart('chart-cumulative-p', 'Cum P(Block)', 'rgb(139,92,246)');
    charts['chart-share-dist'] = makeChart('chart-share-dist', 'Share Dist', 'rgb(16,185,129)');
  }

  // Fase 2.1: clear any manual zoom/pan state so the chart renders the full
  // window again (used when switching ranges or pressing the ⟲ button).
  // Only re-renders when zoom state actually existed (cheap no-op otherwise).
  function _resetChartZoom(chart) {
    if (!chart || !chart.options || !chart.options.scales || !chart.options.scales.x) return;
    const hadZoom = chart.options.scales.x.min !== undefined || chart.options.scales.x.max !== undefined;
    delete chart.options.scales.x.min;
    delete chart.options.scales.x.max;
    if (hadZoom) chart.update('none');
  }

  function bindChartRanges() {
    document.querySelectorAll('.chart-range').forEach(row => {
      const target = row.dataset.target;
      // Only real range chips carry data-range; the ⟲ reset button (data-zoom-reset)
      // is bound separately below so it is never treated as a range.
      row.querySelectorAll('button[data-range]').forEach(btn => {
        btn.addEventListener('click', () => {
          row.querySelectorAll('button[data-range]').forEach(b => b.classList.remove('active'));
          btn.classList.add('active');
          // Fase 2.2: use the BACKEND chart names (hashrate|pool|bestdiff|net).
          // Passing DB column names (worker_hashrate etc.) made every range
          // click fetch an unknown chart and render the panel blank.
          const metricMap = { 'chart-hashrate': 'hashrate', 'chart-pool': 'pool', 'chart-bestdiff': 'bestdiff', 'chart-net': 'net' };
          // Switching ranges resets any manual zoom/pan from the old window.
          _resetChartZoom(charts[target]);
          loadChart(target, metricMap[target] || target.replace('chart-',''), btn.dataset.range);
        });
      });
    });
    // Fase 2.1: explicit ⟲ reset-zoom buttons in each chart toolbar.
    document.querySelectorAll('[data-zoom-reset]').forEach(btn => {
      btn.addEventListener('click', () => {
        _resetChartZoom(charts[btn.dataset.zoomReset]);
      });
    });
  }

  // ── Settings ──
  const SETTINGS_CACHE = { data: null };
  const SETTINGS_SELECTS = { cost_mode: ['none','rental','power'], active_currency: ['USD','BRL','EUR','GBP','JPY','KRW','CNY'], webhook_min_severity: ['INFO','WARN','CRIT','GOLD','SUCCESS'], rental_auto_blacklist_grade: ['A','B','C','D','F'] };
  const SETTINGS_CHECKBOX = { show_test_alerts: true };
  // Didactic hints shown under each settings field so users configure the
  // cost model correctly (Fase: LEASE mode — rental_usd_per_th_day is the
  // rate the LENDER charges, i.e. revenue, not a plain "cost").
  // Pure builder for the Settings → webhook preview (mirrored in JS tests).
  // Shows the operator the exact JSON payload that polling fires per alert.
  function webhookPreviewPayload(severity, message, worker, address) {
    return {
      event: 'cypher65_war_room_alert',
      severity: severity || 'WARN',
      category: 'alert',
      message: message || '⚠ [WARN] exemplo de alerta — configuração de webhook do CYPHER65',
      ts: Math.floor(Date.now() / 1000),
      worker: worker || 'primary',
      address: address || '',
    };
  }

  const SETTINGS_HINTS = {
    mrr_api_key: 'MiningRigRentals API key — crie em miningrigrentals.com → My Account → API Access (gerada uma vez, junto com o secret). Destrava histórico + performance no painel RENTALS.',
    mrr_api_secret: 'MiningRigRentals API secret — par da key acima (mostrado uma vez na criação). Guarde com segurança; nunca compartilhe.',
    braiins_api_key: 'Braiins Hashpower owner token (mostrado UMA vez no registro em hashpower.braiins.com; se perder, regenere em Settings → API Tokens) — destrava bids, contratos e saldo no painel RENTALS. Header de auth: `apikey`.',
    cost_mode: 'none = no cost · rental = pay per TH/s rented · power = rig kWh cost',
    rental_usd_per_th_day: '📤 LEASE: o que VOCÊ cobra ao alugar seu hashrate (receita) · 📦 RENTAL: o que você paga para alugar hashrate. Usado no modo LEASE do Profitability.',
    power_watts: 'Consumo do rig (W) — usado para o custo de energia no modo POWER e no LEASE.',
    power_kwh_usd: 'Tarifa de eletricidade ($/kWh) — usada junto com power_watts no modo POWER e no LEASE.',
    pool_fee_pct: 'Taxa da pool (%) aplicada à receita de mineração.',
    active_currency: 'Moeda exibida nos valores fiat (USD|BRL|EUR|GBP|JPY|KRW|CNY).',
    rental_pl_alert_pct: 'ALERTA CFO: dispara webhook + push quando um aluguel FECHA com P/L econômico abaixo deste % (ex: -50). Vazio ou 0 = desativado. Como o P/L vs yield costuma ser muito negativo, use um limiar realista (ex: -90) para só alertar os piores — ou deixe vazio para desligar. (Sem network hashrate, a checagem usa overpay vs preço de mercado.)',
    rental_pl_alert_window_hours: 'Janela: só alerta aluguéis que FECHARAM nas últimas N horas — evita enxurrada de alertas antigos ao habilitar a primeira vez.',
    rental_market_overpay_pct: 'ALERTA OVERPAY: dispara webhook + push quando o preço PAGO de um aluguel ficar este % ACIMA do mercado NA HORA DA COMPRA (preço acordado vs mercado histórico na data do start). Ex: 100 = alerta se pagou 2× o mercado. Vazio ou 0 = desativado. Dispara também para aluguéis ativos comprados nas últimas N horas.',
    rentals_min_delivery_pct: 'ANÁLISE DE RENDIMENTO (CSV): entrega mínima aceitável por aluguel (default 90). Abaixo dela o aluguel é marcado cancelled_performance no CSV e o reembolso devido é calculado (regra MRR: <80% = total; 80%..mín = proporcional).',
    rental_market_arb_pct: 'ALERTA ARBITRAGEM: dispara webhook + push quando o mercado AGORA estiver este % ABAIXO dos seus custos históricos (seus próprios aluguéis — abra o painel RENTALS uma vez para popular). Compara com 3 referências: CUSTO MÉDIO anunciado, CUSTO EFETIVO com entrega real (paid ÷ TH·h entregues — sobe quando a entrega é <100%) e o ÚLTIMO aluguel; a referência MAIS ALTA dispara o sinal. Ex: 30 = alerta quando o mercado estiver ≥30% mais barato que sua referência mais cara — janela de compra. Vazio ou 0 = desativado. 100% local, custo zero de provider.',
    rental_market_arb_cooldown_hours: 'Cooldown da arbitragem: repete o alerta de oportunidade no máximo 1× a cada N horas (padrão 24). Mercado barato persistente avisa diariamente, sem spam.',
    rental_reco_worse_alert: 'ALERTA RECOMENDAÇÃO ACEITA PIOROU: dispara webhook + push quando um rig que você blacklistou (recomendação aceita) termina com veredito PIOROU — ele voltou a entregar mal DEPOIS da exclusão, o blacklist não resolveu. 0/1, default 0 (off). Decisões revogadas nunca disparam.',
    rental_auto_exclude_alert: 'ALERTA AUTO-EXCLUSÃO: dispara webhook + push quando o sweep automático excluir um rig por sub-entrega (grade ≤ seu floor com amostras suficientes). A mensagem inclui a causa (entrega %, amostras, régua vigente). 0/1, default 0 (off).',
    rental_auto_blacklist_min_samples: 'AUTO-EXCLUSÃO: mínimo de amostras de entrega antes de excluir automaticamente um rig que entrega mal (default 2). Quanto mais alto, mais conservadora a decisão do piloto — precisa de mais histórico para excluir.',
    rental_auto_blacklist_grade: 'AUTO-EXCLUSÃO: o rig é auto-excluído quando a grade de entrega é PIOR OU IGUAL a esta letra (default F = só F). Ex: D exclui D e F; C exclui C, D e F. Grades vêm do trust score (median delivery + consistência).',
  };
  function renderSettingsForm() {
    const box = dom.settingsBody;
    if (!box) return;
    const settings = SETTINGS_CACHE.data;
    if (!settings || !Object.keys(settings).length) {
      box.innerHTML = '<div class="mkt-empty" style="padding:16px;text-align:center">settings unavailable</div>';
      return;
    }
    const order = ['cost_mode','rental_usd_per_th_day','power_watts','power_kwh_usd','btc_block_reward','btc_avg_tx_fee','pool_fee_pct','orphan_rate_pct','active_currency','active_fiat','stale_share_minutes','hashrate_drop_pct','webhook_url','webhook_min_severity','rental_pl_alert_pct','rental_pl_alert_window_hours','rental_market_overpay_pct','rental_market_arb_pct','rental_market_arb_cooldown_hours','rental_reco_worse_alert','rental_auto_exclude_alert','rentals_min_delivery_pct','rental_auto_blacklist_min_samples','rental_auto_blacklist_grade','show_test_alerts','mrr_api_key','mrr_api_secret','braiins_api_key'];
    const keys = Object.keys(settings).sort((a,b) => {
      const ia = order.indexOf(a), ib = order.indexOf(b);
      return (ia<0?99:ia) - (ib<0?99:ib);
    });
    let html = '<div style="display:flex;flex-direction:column;gap:8px;padding:4px 0">';
    keys.forEach(k => {
      const s = settings[k] || {};
      const val = s.secret ? '' : ((s.value !== undefined && s.value !== null && s.value !== '') ? s.value : s.default);
    const label = escapeHtml(s.label || k);
    const hint = SETTINGS_HINTS[k] ? `<small style="color:${cssVar('--text-tertiary')};font-size:10px;line-height:1.3">${escapeHtml(SETTINGS_HINTS[k])}</small>` : '';
    if (SETTINGS_SELECTS[k]) {
      const opts = SETTINGS_SELECTS[k].map(o => `<option value="${o}" ${String(val)===o?'selected':''}>${o}</option>`).join('');
      html += `<label style="display:flex;flex-direction:column;gap:2px;font-size:11px"><span>${label}</span><select name="${k}" class="field__input">${opts}</select>${hint}</label>`;
    } else if (SETTINGS_CHECKBOX[k]) {
      html += `<label style="display:flex;gap:6px;font-size:11px;align-items:center"><input type="checkbox" name="${k}" ${String(val)==='1'?'checked':''}> ${label}${hint}</label>`;
    } else {
      const inputType = s.secret ? 'password' : 'text';
      const placeholder = s.secret && s.configured ? 'Configurado — deixe vazio para preservar' : '';
      const configured = s.secret && s.configured ? '<small class="settings-secret-state">✓ configurado · valor nunca é retornado pelo servidor</small>' : '';
      html += `<label style="display:flex;flex-direction:column;gap:2px;font-size:11px"><span>${label}</span><input type="${inputType}" name="${k}" value="${escapeHtml(String(val ?? ''))}" placeholder="${escapeHtml(placeholder)}" autocomplete="new-password" class="field__input">${configured}${hint}</label>`;
    }
    });
    // Credential sanity helpers for the RENTALS providers. Env-var override
    // warning: on a deployed instance (Render) BRAIINS_API_KEY set in the
    // environment silently wins over this field — tell the operator, or they
    // edit the field, nothing changes, and the panel keeps saying "rejected".
    if ((SETTINGS_CACHE.env || {}).braiins_api_key && settings['braiins_api_key']) {
      html += '<div style="margin-top:2px;border:1px solid var(--accent-orange);border-radius:4px;padding:6px 8px;font-size:10px;line-height:1.4;color:var(--text-muted)">⚠ O servidor tem <code>BRAIINS_API_KEY</code> definida como env var — ela <b>SOBRESCREVE</b> o valor abaixo. Remova a env var (Render → Environment) para usar a chave do Settings.</div>';
    }
    // Same override warning for the MRR key/secret pair (Issue #189): the
    // per-user model is Settings-only — env vars are a default-tenant trap
    // that silently wins over the fields below.
    const mrrEnv = (SETTINGS_CACHE.env || {}).mrr_api_key || (SETTINGS_CACHE.env || {}).mrr_api_secret;
    if (mrrEnv && (settings['mrr_api_key'] || settings['mrr_api_secret'])) {
      html += '<div style="margin-top:2px;border:1px solid var(--accent-orange);border-radius:4px;padding:6px 8px;font-size:10px;line-height:1.4;color:var(--text-muted)">⚠ O servidor tem <code>MRR_API_KEY/MRR_API_SECRET</code> como env var — elas <b>SOBRESCREVEM</b> os valores abaixo. Remova as env vars (Render → Environment) para usar as chaves do Settings.</div>';
    }
    // "Test connection" for Braiins: probes the live API and reports the same
    // verdict the RENTALS panel derives (ok / rejected / missing).
    if (settings['braiins_api_key']) {
      html += '<div style="display:flex;align-items:center;gap:6px;margin-top:2px;flex-wrap:wrap">' +
        '<button type="button" class="btn btn--primary btn--mini" id="braiins-test">' + _ic('key', 12, true) + 'TESTAR CHAVE BRAIINS</button>' +
        '<span id="braiins-test-status" style="font-size:10px;color:var(--text-muted)"></span>' +
        '</div>';
    }
    if (settings['mrr_api_key'] && settings['mrr_api_secret']) {
      html += '<div style="display:flex;align-items:center;gap:6px;margin-top:2px;flex-wrap:wrap">' +
        '<button type="button" class="btn btn--primary btn--mini" id="mrr-test">' + _ic('key', 12, true) + 'TESTAR MRR (READ-ONLY)</button>' +
        '<span id="mrr-test-status" style="font-size:10px;color:var(--text-muted)"></span>' +
        '</div>';
    }
    // Webhook preview + test send (UX audit Quick Win): the operator sees
    // the exact JSON payload fired per alert, and can validate the channel
    // without waiting for a real event. Only rendered when a URL is actually
    // configured — otherwise the ENVIAR TESTE button would dead-end in a 400.
    const whConfigured = (settings['webhook_url'] && settings['webhook_url'].value) ? String(settings['webhook_url'].value).trim() : '';
    if (whConfigured) {
      html += '<div class="wh-preview" style="margin-top:6px;border:1px dashed var(--border);border-radius:4px;padding:8px">' +
        '<div style="font-size:10px;color:var(--text-tertiary);letter-spacing:0.06em">WEBHOOK PREVIEW — payload enviado a cada alerta (JSON)</div>' +
        '<pre id="wh-preview-payload" style="background:' + cssVar('--bg-input') + ';padding:6px;border-radius:4px;font-size:9px;line-height:1.5;overflow:auto;margin:6px 0;max-height:140px;color:var(--green)"></pre>' +
        '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">' +
        '<button type="button" class="btn btn--primary btn--mini" id="wh-send-test">' + _ic('send', 12, true) + 'ENVIAR TESTE</button>' +
        '<span id="wh-test-status" style="font-size:10px;color:var(--text-muted)"></span>' +
        '</div></div>';
    }
    // "Test alert" for the AUTO-EXCLUSION family (Issue #104): fires the SAME
    // message the sweep dispatches on a real exclusion, through the SAME
    // builders (send_webhook_for_alert + notify_tenant_alert), synchronously —
    // webhook + push verdict in one click. Always visible so the operator can
    // validate the tenant config BEFORE enabling rental_auto_exclude_alert.
    if (settings['rental_auto_exclude_alert']) {
      html += '<div style="margin-top:6px;border:1px dashed var(--border);border-radius:4px;padding:8px">' +
        '<div style="font-size:10px;color:var(--text-tertiary);letter-spacing:0.06em">ALERTA AUTO-EXCLUSÃO — teste do canal (webhook + push)</div>' +
        '<div style="font-size:10px;color:var(--text-muted);line-height:1.4;margin:4px 0 6px">Envia uma mensagem de exemplo do tipo que o piloto dispara quando o sweep exclui um rig por sub-entrega. Nenhuma exclusão real é feita.</div>' +
        '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">' +
        '<button type="button" class="btn btn--primary btn--mini" id="ae-send-test">' + _ic('flask', 12, true) + 'TESTAR ALERTA</button>' +
        '<span id="ae-test-status" style="font-size:10px;color:var(--text-muted)"></span>' +
        '</div></div>';
    }
    html += '</div>';
    box.innerHTML = html;
    // Live-update the preview as the operator edits webhook fields, and wire
    // the "send test" button to POST a real sample payload to the channel.
    const whInput = box.querySelector('input[name="webhook_url"]');
    const whSev = box.querySelector('select[name="webhook_min_severity"]');
    const whPreview = document.getElementById('wh-preview-payload');
    function updateWhPreview() {
      if (!whPreview) return;
      const sev = whSev ? whSev.value : (settings['webhook_min_severity'] && settings['webhook_min_severity'].value) || 'WARN';
      whPreview.textContent = JSON.stringify(webhookPreviewPayload(sev), null, 2);
    }
    if (whInput && whPreview) {
      whInput.addEventListener('input', updateWhPreview);
      if (whSev) whSev.addEventListener('change', updateWhPreview);
      updateWhPreview();
    }
    const whTestBtn = document.getElementById('wh-send-test');
    if (whTestBtn) {
      whTestBtn.addEventListener('click', async function() {
        const st = document.getElementById('wh-test-status');
        if (st) { st.textContent = 'enviando…'; st.style.color = 'var(--text-muted)'; }
        try {
          const r = await authFetch('/api/settings/test-webhook', { method: 'POST' });
          const d = await r.json();
          if (st) {
            if (r.ok && d.success) { st.textContent = '✓ enviado (HTTP ' + d.status_code + ')'; st.style.color = 'var(--green)'; }
            else { st.textContent = '✗ ' + (d.error || ('HTTP ' + r.status)); st.style.color = 'var(--accent-red)'; }
          }
        } catch (e) {
          if (st) { st.textContent = '✗ network error: ' + e.message; st.style.color = 'var(--accent-red)'; }
        }
      });
    }
    const braiinsTestBtn = document.getElementById('braiins-test');
    if (braiinsTestBtn) {
      braiinsTestBtn.addEventListener('click', async function() {
        const st = document.getElementById('braiins-test-status');
        if (st) { st.textContent = 'testando… (pode levar ~10s)'; st.style.color = 'var(--text-muted)'; }
        try {
          // The probe can hit up to 4 Braiins endpoints — never let the button
          // hang indefinitely (AbortController 20s hard cap).
          const ctrl = new AbortController();
          const _timer = setTimeout(() => ctrl.abort(), 20000);
          const r = await authFetch('/api/settings/test-braiins', { method: 'POST', signal: ctrl.signal });
          clearTimeout(_timer);
          const d = await r.json();
          if (!st) return;
          if (r.ok && d.success) {
            st.textContent = '✓ chave aceita — ' + d.contracts + ' contrato(s)/bid(s) encontrados' + (d.env_override ? ' (via env var)' : '');
            st.style.color = 'var(--green)';
          } else if (!d.configured) {
            st.textContent = '✗ nenhuma chave configurada — cole o owner token acima' + (d.env_override ? ' (env var presente, mas inválida)' : '');
            st.style.color = 'var(--accent-red)';
          } else {
            st.textContent = '✗ ' + (d.error || 'falhou') + (d.env_override ? ' — a env var BRAIINS_API_KEY SOBRESCREVE este campo' : '');
            st.style.color = 'var(--accent-red)';
          }
        } catch (e) {
          if (st) { st.textContent = '✗ network error: ' + e.message; st.style.color = 'var(--accent-red)'; }
        }
      });
    }
    const mrrTestBtn = document.getElementById('mrr-test');
    if (mrrTestBtn) {
      mrrTestBtn.addEventListener('click', async function() {
        const st = document.getElementById('mrr-test-status');
        if (st) { st.textContent = 'testando /whoami…'; st.style.color = 'var(--text-muted)'; }
        const ctrl = new AbortController();
        const timer = setTimeout(() => ctrl.abort(), 20000);
        try {
          const r = await authFetch('/api/settings/test-mrr', { method: 'POST', signal: ctrl.signal });
          const d = await r.json();
          if (!st) return;
          const labels = {
            accepted: '✓ credenciais aceitas pelo MRR',
            missing: '✗ key e secret não estão configuradas',
            rejected: '✗ MRR rejeitou a credencial — regenere o par key/secret',
            timeout: '✗ timeout ao alcançar o MRR',
            provider_unavailable: '✗ MRR indisponível ou resposta inválida',
            upstream_error: '✗ MRR respondeu HTTP ' + (d.http_status || 'erro'),
            unexpected_response: '✗ resposta de autenticação não reconhecida',
          };
          st.textContent = labels[d.status] || ('✗ diagnóstico: ' + (d.status || 'erro'));
          if (d.env_override) st.textContent += ' · credencial vem da env var';
          st.style.color = d.status === 'accepted' ? 'var(--green)' : 'var(--accent-red)';
        } catch (e) {
          if (st) { st.textContent = e.name === 'AbortError' ? '✗ timeout local (20s)' : '✗ network error'; st.style.color = 'var(--accent-red)'; }
        } finally {
          clearTimeout(timer);
        }
      });
    }
    const aeTestBtn = document.getElementById('ae-send-test');
    if (aeTestBtn) {
      aeTestBtn.addEventListener('click', async function() {
        const st = document.getElementById('ae-test-status');
        if (st) { st.textContent = 'enviando…'; st.style.color = 'var(--text-muted)'; }
        try {
          const r = await authFetch('/api/settings/test-auto-exclude-alert', { method: 'POST' });
          const d = await r.json();
          if (!st) return;
          if (!r.ok) {
            st.textContent = '✗ ' + (d.error || ('HTTP ' + r.status));
            st.style.color = 'var(--accent-red)';
            return;
          }
          if (d.success) {
            const bits = [];
            if (d.webhook_ok) bits.push('webhook ✓');
            if (d.push_targets > 0) bits.push('push → ' + d.push_targets + ' dispositivo(s)');
            // Green success must NOT mask a dead webhook — that's the config
            // failure this button exists to catch (e.g. broken URL + push ok).
            const whWarn = (d.webhook_configured && !d.webhook_ok) ? ('⚠ webhook: ' + (d.webhook_reason || 'falhou')) : '';
            st.textContent = '✓ ' + bits.join(' · ') + (whWarn ? ' · ' + whWarn : '');
            st.style.color = whWarn ? 'var(--accent-orange)' : 'var(--green)';
          } else {
            const why = d.webhook_configured
              ? 'webhook: ' + (d.webhook_reason || 'falhou') + (d.push_targets === 0 ? ' · push sem dispositivos' : '')
              : 'nenhum canal entregou';
            st.textContent = '✗ ' + why + (d.guidance ? ' — ' + d.guidance : '');
            st.style.color = 'var(--accent-red)';
          }
        } catch (e) {
          if (st) { st.textContent = '✗ network error: ' + e.message; st.style.color = 'var(--accent-red)'; }
        }
      });
    }
  }
  async function loadSettings() {
    try {
      const r = await authFetch('/api/settings');
      const _j = await r.json();
      SETTINGS_CACHE.data = (_j.settings || []).reduce((acc, s) => { acc[s.key] = s; return acc; }, {});
      // env_overrides: which credentials are set as env vars on the SERVER —
      // they silently beat the field below (Render deploy gotcha).
      SETTINGS_CACHE.env = _j.env_overrides || {};
      renderSettingsForm();
    } catch (e) {}
  }
  function openSettingsModal() {
    openModalAnimated(dom.settingsModal);
    if (dom.settingsBody && !dom.settingsBody.innerHTML.trim()) renderSettingsForm();
  }
  function closeSettingsModal() { closeModalAnimated(dom.settingsModal); }
  dom.settingsModal?.addEventListener('click', (e) => { if (e.target.matches('[data-close]')) closeSettingsModal(); });
  dom.openSettings?.addEventListener('click', openSettingsModal);

  // ── LN Payment ──
  var _lnPaying = false;

  // Populate LN address from support config on open
  function _populateLNAddress() {
    var el = document.getElementById('support-ln-address');
    if (!el || el.textContent !== '—') return;
    fetch('/api/support-config').then(function(r) { return r.json(); }).then(function(cfg) {
      var ln = cfg.methods && cfg.methods.find(function(m) { return m.id === 'lightning'; });
      if (ln && ln.address) el.textContent = ln.address;
    }).catch(function() { /* support config not available */ });
  }

  // ── Render donation methods into the compact bar + full modal grid ──
  // Fixes the orphaned containers (#support-bar-methods / #support-modal-grid)
  // which had CSS + a copy handler but were never populated by JS. The copy
  // button reads the previous sibling's data-copy attribute (see FASE 3).
  function renderSupportMethods() {
    fetch('/api/support-config').then(function(r) { return r.json(); }).then(function(cfg) {
      var methods = (cfg && cfg.methods) || [];
      var manifesto = cfg && cfg.manifesto ? cfg.manifesto : '';

      // Manifesto (authored, cypherpunk) into the dedicated modal block.
      // Injected BEFORE the methods guard so it renders even if the config
      // ever ships with an empty methods list.
      var maniEl = document.getElementById('support-modal-manifesto');
      if (maniEl && manifesto) {
        maniEl.innerHTML = manifesto.split('\n').map(function(line) {
          if (!line.trim()) return '<br>';
          return line.replace(/^— (.*)$/, '<span class="support-modal__sign">— $1</span>');
        }).join(' ');
      }

      if (!methods.length) return;

      // Compact chips for the fixed footer bar
      var bar = document.getElementById('support-bar-methods');
      if (bar) {
        bar.innerHTML = methods.map(function(m) {
          return '<span class="support-method support-bar__method" title="' + escapeHtml(m.label) + '">' +
            '<span class="support-method-tag" style="color:' + escapeHtml(m.color || cssVar('--green')) + '">' + escapeHtml(m.icon || '₿') + ' ' + escapeHtml(m.label) + '</span>' +
            '<span class="support-method-addr" title="' + escapeHtml(m.label) + ': ' + escapeHtml(m.address) + '" data-copy="' + escapeHtml(m.address) + '">' + escapeHtml(m.address) + '</span>' +
            '<button class="support-method-copy" data-copy-btn aria-label="Copy ' + escapeHtml(m.label) + ' address">⧉</button>' +
            '</span>';
        }).join('');
      }

      // Full cards for the modal grid
      var grid = document.getElementById('support-modal-grid');
      if (grid) {
        grid.innerHTML = methods.map(function(m) {
          return '<div class="support-modal__card">' +
            '<div class="support-modal__card-icon" style="color:' + escapeHtml(m.color || cssVar('--green')) + '">' + escapeHtml(m.icon || '₿') + '</div>' +
            '<div class="support-modal__card-label">' + escapeHtml(m.label) + '</div>' +
            (m.note ? '<div class="support-modal__card-note">' + escapeHtml(m.note) + '</div>' : '') +
            '<div class="support-modal__card-addr" data-copy="' + escapeHtml(m.address) + '">' + escapeHtml(m.address) + '</div>' +
            '<button class="support-modal__card-copy" data-copy-btn>⧉ copy</button>' +
            '</div>';
        }).join('');
      }

      // LN recipient row — same config object, no second fetch needed
      var lnEl = document.getElementById('support-ln-address');
      var ln = methods.find(function(m) { return m.id === 'lightning'; });
      if (lnEl && ln && ln.address && lnEl.textContent === '—') {
        lnEl.textContent = ln.address;
      }
    }).catch(function() { /* support config not available */ });
  }

  // ── Recent Donations list (Support modal) ──
  // Fed by GET /api/donations. Shows total + recent confirmed donations so
  // the operator can answer "como saber quem doou".
  function loadDonations() {
    authFetch('/api/donations').then(function(r) { return r.json(); }).then(function(d) {
      var box = document.getElementById('support-modal-donations');
      if (!box) return;
      var stats = document.getElementById('donations-stats');
      var list = document.getElementById('donations-list');
      if (!stats || !list) return;
      var don = d.donations || [];
      if (!don.length) {
        box.style.display = 'none';
        return;
      }
      box.style.display = '';
      var total = d.total || 0;
      var totalSat = d.total_sat || 0;
      stats.textContent = total + ' doação' + (total === 1 ? '' : 'ões') + ' · ' + (totalSat >= 1e8 ? (totalSat / 1e8).toFixed(8).replace(/\.?0+$/, '') + ' BTC' : totalSat.toLocaleString('en-US') + ' sats') + ' recebidos';
      list.innerHTML = don.slice(0, 6).map(function(row) {
        var methodIcon = { lightning: '⚡', btc: '₿', hashpower: '⛏' }[row.method] || '♥';
        var amt = row.amount_sat != null ? escapeHtml(row.amount_sat >= 1e8 ? (row.amount_sat / 1e8).toFixed(8).replace(/\.?0+$/, '') + ' BTC' : row.amount_sat.toLocaleString('en-US') + ' sats') : '—';
        var t = new Date((row.ts || 0) * 1000);
        var ts = t.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
        var proof = row.txid ? escapeHtml(row.txid.slice(0, 10)) + '…' : (row.preimage ? 'preimage ' + escapeHtml(row.preimage.slice(0, 10)) + '…' : '');
        // verified = onchain (mempool watcher) or manual (operator-confirmed);
        // webln = client-reported, not verified on-chain
        var badge = row.source !== 'webln'
          ? '<span class="donation-row__badge is-verified" title="Confirmado on-chain (mempool)">✓</span>'
          : '<span class="donation-row__badge" title="Relatado pelo doador via WebLN — não verificado on-chain">~</span>';
        return '<div class="donation-row">' +
          '<span class="donation-row__icon">' + methodIcon + '</span>' +
          '<span class="donation-row__amt">' + amt + '</span>' +
          '<span class="donation-row__proof mono">' + (proof ? proof : escapeHtml(row.note || '')) + '</span>' +
          badge +
          '<span class="donation-row__ts">' + ts + '</span>' +
          '</div>';
      }).join('');
    }).catch(function() { /* donations not available */ });
  }

  // Render once on boot so the footer bar has the chips immediately
  renderSupportMethods();
  loadDonations();
  // Listen for support panel opening — only the ◈ Details button opens the
  // modal (clicks on the compact bar's copy chips must NOT open the full
  // panel); both entry points still populate the LN address.
  document.addEventListener('click', function _onSupportOpen(e) {
    var onExpand = e.target.closest('#support-expand-btn');
    if (onExpand || e.target.closest('#support-bar-methods')) {
      if (onExpand) {
        var panel = document.getElementById('support-panel');
        if (panel) openModalAnimated(panel);
      }
      setTimeout(_populateLNAddress, 200);
      // Re-render on open so a failed boot fetch self-heals when the panel
      // is actually opened (same retry semantics as _populateLNAddress).
      setTimeout(renderSupportMethods, 250);
      setTimeout(loadDonations, 300);
    }
  });

  async function sendLNPayment() {
    if (_lnPaying) return;
    _lnPaying = true;
    var invoiceInput = document.getElementById('ln-invoice-input');
    var statusEl = document.getElementById('ln-payment-status');
    if (!invoiceInput || !statusEl) { _lnPaying = false; return; }

    try {
      var invoice = invoiceInput.value.trim();
      if (!invoice) {
        statusEl.textContent = '\u26A0 Please paste a BOLT11 invoice';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }
      // Smart validation: help the donor paste the RIGHT thing. The spark
      // address / lightning addresses / on-chain addrs are NOT BOLT11 —
      // give a specific hint instead of a generic rejection. Flat chain:
      // spark1 → lnurl → lightning-address → on-chain → BOLT12 → BOLT11 ok.
      var lower = invoice.toLowerCase();
      if (lower.indexOf('spark1') === 0) {
        statusEl.textContent = '\u26A0 Essa é a spark address (destino), não um invoice. Gere um invoice BOLT11 (lnbc1...) na sua wallet para pagar aqui.';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }
      if (lower.indexOf('lnurl') === 0) {
        statusEl.textContent = '\u26A0 Isso é um lnurl, não um invoice BOLT11. Cole o invoice (lnbc1...) que sua wallet gerou para pagar.';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }
      if (lower.indexOf('@') > 0) {
        statusEl.textContent = '\u26A0 Isso é um lightning address (user@domínio). Cole o invoice BOLT11 (lnbc1...) gerado na sua wallet.';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }
      if (lower.indexOf('bc1') === 0 || lower.indexOf('1') === 0 || lower.indexOf('3') === 0) {
        statusEl.textContent = '\u26A0 Isso é um endereço on-chain (BTC). Para Lightning, cole um invoice BOLT11 (lnbc1...).';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }
      if (lower.indexOf('lno1') === 0) {
        statusEl.textContent = '\u26A0 Isso é um offer BOLT12 (lno1...), ainda não suportado. Cole um invoice BOLT11 (lnbc1...).';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }
      if (lower.indexOf('lnbc') !== 0 && lower.indexOf('lntb') !== 0) {
        statusEl.textContent = '\u26A0 Invoice inválido — um invoice BOLT11 começa com lnbc1 (mainnet) ou lntb1 (testnet).';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }
      // Extract the invoice amount (msat → sat) for the donation record.
      // Shared BOLT11 parser — see bolt11AmountSats() (Issue 249).
      var invAmtSat = bolt11AmountSats(invoice);

      statusEl.textContent = '\uD83D\uDD0D Connecting Lightning wallet...';
      statusEl.className = 'support-modal__ln-status support-modal__ln-status--pending';

      var provider = await detectWebLN(5000);
      if (!provider) {
        statusEl.textContent = '\u26A0 No WebLN wallet detected. Install Alby or Joule browser extension.';
        statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
        return;
      }

      statusEl.textContent = '\uD83D\uDD11 Requesting permission to pay...';
      await provider.enable();

      statusEl.textContent = '\uD83D\uDCB8 Sending payment...';
      var result = await provider.sendPayment(invoice);
      var preimage = result && result.preimage ? result.preimage : '';
      var shortPreimage = preimage ? preimage.slice(0, 16) + '...' : '';
      statusEl.innerHTML = '\u2713 Payment sent! ' + (shortPreimage ? 'Preimage: <code class="mono">' + shortPreimage + '</code>' : '') + '<br><span class="support-modal__ln-footnote">Check your wallet for confirmation.</span>';
      statusEl.className = 'support-modal__ln-status support-modal__ln-status--success';
      invoiceInput.value = '';
      _weblnProvider = provider;
      // Record the donation server-side (dedup by preimage) so the operator
      // can see it in the Recent Donations list + Alerts panel. Sends the
      // invoice amount (parsed above) so the list shows sats, not '—'.
      if (preimage) {
        try {
          authFetch('/api/donations', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ method: 'lightning', preimage: preimage, amount_sat: invAmtSat, source: 'webln' })
          }).then(function() { loadDonations(); }).catch(function() {});
        } catch (e) { /* non-fatal */ }
      }
    } catch (e) {
      statusEl.textContent = '\u2717 Payment ' + (e.message && e.message.indexOf('denied') !== -1 ? 'denied' : 'failed') + ': ' + (e.message || 'unknown error');
      statusEl.className = 'support-modal__ln-status support-modal__ln-status--error';
    } finally {
      _lnPaying = false;
    }
  }

  // Wire up LN Pay button
  document.addEventListener('click', function(e) {
    if (e.target.closest('#ln-pay-btn')) sendLNPayment();
  });

  // ── Wallet modal ──
  function openWalletModal() {
    openModalAnimated(dom.walletModal);
    // Fill current address info (NOT CONNECTED state when no wallet yet)
    var walletConnected = !!window.BTC_ADDRESS;
    if (dom.walletCurrentAddr) {
      dom.walletCurrentAddr.textContent = walletConnected ? fmt.chunkAddr(window.BTC_ADDRESS) : 'NOT CONNECTED';
      dom.walletCurrentAddr.classList.toggle('wallet-current__addr--empty', !walletConnected);
    }
    if (dom.walletCurrentWorker) dom.walletCurrentWorker.textContent = walletConnected ? (window.WORKER_NAME || '—') : '—';
    if (dom.walletCurrentStatus) {
      dom.walletCurrentStatus.style.display = 'inline-flex';
      dom.walletCurrentStatus.textContent = walletConnected ? '● CONNECTED' : '○ NO WALLET CONNECTED';
      dom.walletCurrentStatus.classList.toggle('wallet-current__status--ok', walletConnected);
      dom.walletCurrentStatus.classList.toggle('wallet-current__status--empty', !walletConnected);
    }
    if (dom.walletAddressInput) dom.walletAddressInput.value = '';
    if (dom.walletWorkerInput) dom.walletWorkerInput.value = '';
    if (dom.walletStatus) dom.walletStatus.textContent = '';
    // P0-4: render the identity card (QR + checksum + health) from the
    // latest snapshot — a wallet may already be connected on open.
    renderWalletIdentity(prevSnapshot);
    // Focus the address input
    setTimeout(() => dom.walletAddressInput?.focus(), 100);
    // ── Hitórico de wallets ──
    fetchWalletHistory();
  }
  function closeWalletModal() {
    closeModalAnimated(dom.walletModal);
    if (dom.walletStatus) dom.walletStatus.textContent = '';
  }
  // Onboarding CTA: show when NO wallet is connected, hide once one is
  function toggleWalletCTA() {
    var cta = document.getElementById('wallet-cta');
    if (!cta) return;
    cta.style.display = window.BTC_ADDRESS ? 'none' : 'flex';
  }
  // CTA button opens the same wallet modal as the topbar ⚡ CONNECT
  document.getElementById('wallet-cta-open')?.addEventListener('click', openWalletModal);
  // Show the onboarding CTA immediately at boot (no wallet yet) instead of
  // waiting for the first snapshot render (~15s)
  toggleWalletCTA();
  dom.walletModal?.addEventListener('click', (e) => { if (e.target.matches('[data-close]')) closeWalletModal(); });
  dom.openWallet?.addEventListener('click', openWalletModal);
  document.getElementById('webln-connect-btn')?.addEventListener('click', connectWebLN);

  // Save wallet

  // ── FASE 2: Fetch wallet history ──
  async function fetchWalletHistory() {
    try {
      var resp = await authFetch('/api/wallet/history');
      var data = await resp.json();
      if (data.success && data.history) {
        var list = document.getElementById('wallet-history-list');
        if (list) {
          list.innerHTML = '';
          data.history.forEach(function(entry) {
            var li = document.createElement('button');
            li.className = 'wallet-history__item';
            li.innerHTML = '<span class="mono">' + escapeHtml(entry.address.slice(0, 10)) + '...</span> <span class="mute">' + escapeHtml(entry.worker || '') + '</span>';
            li.onclick = function() {
              var input = document.getElementById('wallet-address-input');
              if (input) input.value = entry.address;
              var wInput = document.getElementById('wallet-worker-input');
              if (wInput && entry.worker) wInput.value = entry.worker;
            };
            list.appendChild(li);
          });
        }
      }
    } catch(e) {
      console.warn('[wallet history]', e);
    }
  }  // ── Personalized wallet greetings (by address) ───────────────────
  // Wallets in this map are community / early-supporters: they receive a
  // personalized welcome AND hold FULL & FREE access to the tool (policy:
  // every greeted wallet is entitled).
  const WALLET_GREETINGS = {
    'bc1qftl45m5jq7hjd0n62yuxesmss478xl2wvfkeed': '👋 Bem vindo barone (barone club)',
    'bc1qffk82prrxn84e8y9l0z5yflsqclhyc9ptphgmf': '👋 Bem vindo filipe silva — comunidade bitminer33',
    'bc1q029y2atdtvth4puv2mm5w49m32n278jtz2sxqn': '👋 Bem vindo DIGO GARABELI — acesso FULL & FREE',
    'dhr7a2ihqou5w5r5cpvsuvcnw4jg32qlwx': '👋 Bem vindo DIGO GARABELI — acesso FULL & FREE',
    '1473pql42jvtwxaaxcvsocrf6ytb8teted': '👋 Bem vindo DIGO GARABELI — acesso FULL & FREE',
  };

  function walletGreeting(address) {
    if (!address) return null;
    return WALLET_GREETINGS[String(address).toLowerCase()] || null;
  }

  // Policy: every wallet with a personalized greeting holds FULL & FREE
  // access to the tool. Kept as an explicit helper so the connect flow
  // (and any future gated feature) treats greeted wallets as entitled.
  function walletHasFullAccess(address) {
    return walletGreeting(address) !== null;
  }

dom.walletSave?.addEventListener('click', async () => {
    const status = dom.walletStatus;
    if (!status) return;
    const address = dom.walletAddressInput?.value?.trim() || '';
    if (!address) {
      status.textContent = '⚠ paste a BTC address first';
      status.style.color = 'var(--accent-red)';
      return;
    }
    status.textContent = '⏳ connecting...';
    status.style.color = 'var(--text-tertiary)';
    try {
      const resp = await authFetch('/api/set-address', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ address }),
      });
      const data = await resp.json();
      if (!resp.ok) {
        status.textContent = '⚠ ' + (data.error || 'request failed');
        status.style.color = 'var(--accent-red)';
        return;
      }
      status.textContent = '✅ connected — updating...';
      status.style.color = 'var(--accent-green)';
      // Update globals
      window.BTC_ADDRESS = data.address;
      toggleWalletCTA(); // instant feedback: hide the onboarding CTA now
      localStorage.setItem('_wallet_connected', 'true');
      showToast('success', 'Wallet connectada: ' + data.address.slice(0, 10) + '...');
      // Personalized welcome for known community wallets
      const greeting = walletGreeting(data.address);
      if (greeting) showToast('success', greeting);
      // Greeted wallets hold FULL & FREE access — surface it so the
      // entitlement is visible, not silent.
      if (walletHasFullAccess(data.address)) {
        showToast('success', '⚡ Acesso FULL & FREE confirmado');
      }
      // HOTFIX: Trigger immediate data fetch after wallet connect
      // This forces an immediate poll instead of waiting ~15s
      window.dispatchEvent(new CustomEvent('wallet-changed', { detail: { address: data.address } }));
      // Update topbar — show just the address
      if (dom.topbarAddress) {
        dom.topbarAddress.textContent = fmt.shortAddr(data.address) || '—';
      }
      // Close modal after a short delay. The refresh itself is handled by
      // the wallet-changed listener (dispatched above) — refreshUntilWalletReady
      // — so no second retry chain is started here.
      setTimeout(() => {
        closeWalletModal();
      }, 300);
    } catch (e) {
      status.textContent = '⚠ network error: ' + e.message;
      status.style.color = 'var(--accent-red)';
    }
  });
  document.getElementById('settings-save')?.addEventListener('click', async () => {
    const form = document.getElementById('settings-body');
    if (!form) return;
    const data = {};
    form.querySelectorAll('input, select, textarea').forEach(el => {
      if (!el.name) return;
      // Secrets/URLs must be trimmed: an owner token pasted with a trailing
      // newline makes the `apikey` header invalid → 401 "key rejected".
      const _trim = ['braiins_api_key', 'mrr_api_key', 'mrr_api_secret', 'webhook_url'].includes(el.name);
      const value = el.type === 'checkbox' ? (el.checked ? '1' : '0') : (_trim ? el.value.trim() : el.value);
      // Credential fields are write-only. Empty means "preserve existing",
      // never "erase"; explicit clearing uses the backend clear contract.
      if (el.type === 'password' && value === '') return;
      data[el.name] = value;
    });
    try {
      const r = await authFetch('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      const result = await r.json();
      const status = document.getElementById('settings-status');
      // Backend POST /api/settings returns {applied:[], rejected:[]} — no `ok`
      // key. Success = zero rejected keys.
      const rejected = (result && result.rejected) || [];
      const savedOk = r.ok && rejected.length === 0;
      if (status) {
        status.textContent = savedOk ? 'SAVED' : 'ERROR';
        status.className = savedOk ? 'badge badge--green' : 'badge badge--red';
        setTimeout(() => { if (status) status.textContent = ''; }, 2000);
      }
      if (savedOk) {
        // Credentials changed → invalidate the lazy RENTALS cache and refetch
        // NOW (the tab may already be activated, so the activation hook alone
        // would never re-run and the panel would keep showing 🔑/⚠).
        _rentalsLoaded = false;
        _rentalsData = null;
        loadRentals();
        if (typeof fetchSnapshot === 'function') fetchSnapshot();
        setTimeout(() => closeSettingsModal(), 800);
      }
    } catch (e) {
      const status = document.getElementById('settings-status');
      if (status) { status.textContent = 'NETWORK ERROR'; status.className = 'badge badge--red'; }
    }
  });

  // ── Export ──
  function openExportModal() { openModalAnimated(dom.exportModal); }
  function closeExportModal() { closeModalAnimated(dom.exportModal); }
  dom.exportModal?.addEventListener('click', (e) => { if (e.target.matches('[data-close]')) closeExportModal(); });
  dom.openExports?.addEventListener('click', openExportModal);

  // ── Keyboard shortcuts ──
  document.addEventListener('keydown', (e) => {
    const anyModalOpen = () => !!document.querySelector('.modal-overlay.modal--open');
    if (e.key.toLowerCase() === 'r' && !anyModalOpen() && document.activeElement.tagName !== 'INPUT' && !e.metaKey && !e.ctrlKey) fetchSnapshot();
    else if (e.key === 'Escape') { closeWalletModal(); closeSettingsModal(); closeExportModal(); }
    else if (e.key.toLowerCase() === 'w' && !anyModalOpen() && document.activeElement.tagName !== 'INPUT' && !e.metaKey && !e.ctrlKey) {
      openWalletModal();
    }
  });

  // → domínio Terminal/SSE extraído para `static/src/39-terminal.js` (RFC 478, Issue 529)
  // FLEET COMMAND CENTER state (fleet-fed panel).
  let _ccLastFleet = [];
  let _ccView = 'grid';
  const _ccHrSeries = [];   // fleet total-HR history (KPI sparkline)
  const _ccHrHist = {};     // per-device HR history (card sparklines)
  const _ccShareSeen = {};  // ticker share dedupe (by ts)
  // → domínio Terminal/SSE extraído para `static/src/39-terminal.js` (RFC 478, Issue 529)

  // → domínio Terminal/SSE extraído para `static/src/39-terminal.js` (RFC 478, Issue 529)

  // Latest dashboard snapshot received via polling/SSE. Terminal commands
  // (status/workers/price) read this instead of fetching /api/snapshot,
  // which internally triggers external hashrate-market offers and can take
  // >1s — the E2E terminal tests only wait 1000ms after Enter.
  let _lastSnapshot = null;

  // → domínio Terminal/SSE extraído para `static/src/39-terminal.js` (RFC 478, Issue 529)

// ══════════════════════════════════════════════════════════════════════
  // POLLING
  // ══════════════════════════════════════════════════════════════════════



  function updateNextPoll() {
    nextPollAt = Date.now() + POLL_MS;
    if (dom.nextPoll) dom.nextPoll.textContent = `${Math.ceil(POLL_MS/1000)}s`;
  }

  // ── Clock ──
  function updateClock() {
    if (dom.clock) dom.clock.textContent = new Date().toLocaleTimeString();
  }

  // ── Snapshot fetch dedup ──
  // Guards against concurrent /api/snapshot fetches (e.g. rapid market-module
  // activations each firing fetchSnapshot) so render() never runs twice in
  // parallel with two different snapshots. The poll loop and manual refreshes
  // both go through fetchSnapshot, so this keeps a single in-flight fetch.
  let _snapshotFetching = false;
  async function fetchSnapshot() {
    if (_snapshotFetching) return;
    _snapshotFetching = true;
    try {
      const r = await fetch('/api/snapshot');
      if (!r.ok) throw new Error('snapshot failed');
      const snap = await r.json();
      _lastSnapshot = snap;
      render(snap);
      fetchAxeFleet();
      updateNextPoll();
    } catch (e) {
      // Sev-1 (UI audit 2026-08): a failed first fetch must NEVER leave the
      // boot skeletons stuck — the old code only logged, so a fetch failure
      // (network, rate limit on mobile) froze the whole dashboard in a
      // skeleton overlay with the status bar stuck at INIT. Hide on EVERY
      // outcome; the panels then show their honest empty/error state.
      hideSkeletons();
      logMessage('ERROR', e.message, 'WARN');
    }
    finally { _snapshotFetching = false; }
  }

  // ── Boot ──
  async function boot() {
    initCharts(); bindChartRanges(); loadSettings(); initMarketControls(); initDecisionMatrixControls(); initCommandCenterControls(); initOperationalOverviewControls(); _initRentalsPanel();
    _initLmEventLogControls();
    initLicensing();  // R1: PRO badge + license state (off-by-default, no-op in open mode)
    fetchTailscale();
    if (typeof fetchRemoteOnboarding === 'function') fetchRemoteOnboarding();
    updateClock(); setInterval(updateClock, 1000);
    // ── Service Worker: unregister old caches, force fresh install ──
    if ('serviceWorker' in navigator) {
      navigator.serviceWorker.getRegistrations().then(registrations => {
        for (const reg of registrations) {
          reg.unregister();
          console.log('[boot] unregistered old SW:', reg.scope);
        }
        // Register fresh with cache bust
        navigator.serviceWorker.register('/sw.js', { scope: '/' }).then(reg => {
          console.log('[boot] new SW registered');
          // Web Push: subscribe after the SW is ready (never blocks boot).
          setTimeout(() => enablePush(reg), 1500);
        }).catch(e => {
          console.warn('[boot] SW registration failed:', e);
        });
      });
      // Web Push bootstrap — registers a per-tenant push subscription with the
      // server so mining alerts reach this browser even when the tab is closed.
      // Degrades silently: no VAPID key → no prompt; permission denied → no-op.
      async function enablePush(reg) {
        try {
          if (!('PushManager' in window)) return;
          if (!reg || typeof reg.pushManager !== 'object') return;
          // Only offer push when the server has VAPID configured.
          let vapidKey = null;
          try {
            const r = await fetch('/api/push/vapid-key');
            if (r.ok) vapidKey = (await r.json()).vapid_public_key || null;
          } catch (e) { /* offline / push unconfigured — skip silently */ }
          if (!vapidKey) return;
          const sub = await reg.pushManager.getSubscription();
          if (sub) return;  // already subscribed
          let permission = 'default';
          try { permission = await Notification.requestPermission(); } catch (e) {}
          if (permission !== 'granted') return;
          const newSub = await reg.pushManager.subscribe({
            userVisibleOnly: true,
            applicationServerKey: urlBase64ToUint8Array(vapidKey),
          });
          const raw = newSub.toJSON();
          // Issue #115: attach the Bearer token when present so the
          // subscription is stored under the CALLER's tenant (JWT sub is the
          // only authority for a non-empty tenant); anonymous visitors still
          // subscribe under the operator tenant with an https:// endpoint.
          const pushHeaders = { 'Content-Type': 'application/json' };
          const tok = (typeof authGetToken === 'function') ? authGetToken() : '';
          if (tok) pushHeaders['Authorization'] = 'Bearer ' + tok;
          const subRes = await fetch('/api/push/subscribe', {
            method: 'POST',
            headers: pushHeaders,
            body: JSON.stringify({ endpoint: raw.endpoint, keys: raw.keys }),
          });
          if (!subRes.ok) {
            // 401 = token revoked/invalid, 429 = per-IP budget hit, … —
            // surface it instead of pretending push is armed. Never retry
            // WITHOUT the token (that would defeat the Issue #115 boundary).
            console.warn('[push] subscribe rejected (' + subRes.status + ') — push not armed');
            return;
          }
          console.log('[push] subscribed for mining alerts');
        } catch (e) {
          console.warn('[push] enable failed (silent):', e && e.message);
        }
      }
      // VAPID applicationServerKey expects a Uint8Array.
      function urlBase64ToUint8Array(base64String) {
        const padding = '='.repeat((4 - (base64String.length % 4)) % 4);
        const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/');
        const rawData = atob(base64);
        const output = new Uint8Array(rawData.length);
        for (let i = 0; i < rawData.length; ++i) output[i] = rawData.charCodeAt(i);
        return output;
      }
      // Listen for updates and reload when a new SW takes over
      navigator.serviceWorker.addEventListener('controllerchange', () => {
        console.log('[boot] new SW activated — reloading');
        window.location.reload();
      });
    }

    showSkeletons();
    // Sev-1 watchdog (UI audit 2026-08): the first fetch has NO timeout — if
    // it hangs (network blackout, proxy stall) the boot skeletons would stay
    // forever. Force-hide after 20s so the panels degrade to their honest
    // empty/error state instead of a frozen skeleton screen.
    setTimeout(function () { hideSkeletons(); }, 20000);
    initLeaderboardPager();
    initFleetCommandCenterControls();
    initAxeFleetControls();
    initAxeFleetControls();
    initAuth();
    initThemeToggle();
    initInstanceIndicator();
    _liveTermInit();
    await fetchSnapshot();
    setInterval(fetchSnapshot, POLL_MS);
    // ── SSE live stream ── subscribe to push updates at ~3s intervals
    // Fallback: if EventSource fails, the regular 15s poll still works.
    try {
      if (typeof EventSource !== 'undefined') {
        var es = new EventSource('/api/stream');
        var sseRetries = 0;
        var sseLastErrorTs = 0;
        var sseLastFleetFetch = 0;
        es.onmessage = function(e) {
          try {
            var msg = JSON.parse(e.data);
            if (msg && msg.type === 'live') {
              applyLiveMetrics(msg);
              return;
            }
            if (msg && msg.ts) {
              _lastSnapshot = msg;
              render(msg);
              var now = Date.now();
              if (now - sseLastFleetFetch > 10000) {
                sseLastFleetFetch = now;
                fetchAxeFleet();
              }
            }
          } catch(err) { /* ignore parse errors */ }
        };
        es.onerror = function() {
          var now = Date.now();
          // Debounce: ignore errors within 2s (EventSource auto-reconnects)
          if (now - sseLastErrorTs < 2000) return;
          sseLastErrorTs = now;
          sseRetries++;
          if (sseRetries > 5) {
            // After 5 distinct error events (>=2s apart), close SSE and rely on polling
            es.close();
            logMessage('SSE', 'Live stream disconnected — falling back to polling', 'WARN');
          }
        };
      }
    } catch(e) { /* SSE not supported */ }

    logMessage('SYSTEM', 'WAR ROOM ONLINE', 'SUCCESS');
  }

  boot();

  // → domínio Automations/Alerts/Auto-Pilot/Decision Matrix extraído para `static/src/41-automations.js` (RFC 478, Issue 540)

  // ── Sidebar toggle (desktop collapse + mobile open/close) ──
  const sidebar = document.getElementById('sidebar');
  const sidebarBackdrop = document.getElementById('sidebar-backdrop');
  const sidebarOverlay = document.getElementById('sidebar-overlay');
  const sidebarToggle = document.getElementById('sidebar-toggle');
  const sidebarMobileToggle = document.getElementById('sidebar-mobile-toggle');
  const sidebarLinks = document.querySelectorAll('.sidebar__link');

  // MODULE_MAP — módulo → título/descrição do header
  const MODULE_MAP = {
    'dashboard':   { title: 'DASHBOARD',     desc: 'Visão geral — pool, worker e rede' },
    'wallet':      { title: 'WALLET',        desc: 'Conexão e status da wallet' },
    'fleet':       { title: 'FLEET',         desc: 'Visão dos miners' },
    'live':        { title: 'LIVE MINING',   desc: 'Dados ao vivo' },
    'probability': { title: 'BLOCK MODEL',   desc: 'Estatísticas por janela · sem prazo ou previsão' },
    'market':      { title: 'HASH MARKET',   desc: 'Mercado e cotações' },
    'rentals':     { title: 'RENTALS',       desc: 'Performance dos aluguéis (MRR + Braiins)' },
    'alerts':      { title: 'ALERTS',        desc: 'Alertas e eventos' },
    'automations': { title: 'AUTOMATIONS',   desc: 'Regras e automação' },
    'docs':        { title: 'DOCS / GUIDE',  desc: 'Manual de uso' },
    'learning':    { title: 'LEARNING',      desc: 'Bitcoin Academy — whitepaper, livros e Ordinals' },
    'support':     { title: 'SUPPORT',       desc: 'Doação e apoio' },
    'admin':       { title: 'ADMIN · CFO',   desc: 'Operador: pool health + funil PRO + LTV/CAC' },
  };

  function openSidebar() {
    sidebar.classList.add('open');
    if (sidebarBackdrop) sidebarBackdrop.classList.add('visible');
    if (sidebarOverlay) sidebarOverlay.classList.add('visible');
  }
  function closeSidebar() {
    sidebar.classList.remove('open');
    if (sidebarBackdrop) sidebarBackdrop.classList.remove('visible');
    if (sidebarOverlay) sidebarOverlay.classList.remove('visible');
  }
  function toggleSidebar() {
    sidebar.classList.contains('open') ? closeSidebar() : openSidebar();
  }

  if (sidebarToggle) {
    sidebarToggle.addEventListener('click', () => {
      // Em viewport mobile, o ☰ do topbar ABRE a sidebar (não colapsa)
      if (window.innerWidth <= 1100) { toggleSidebar(); return; }
      // CSS usa .sidebar.collapsed (compatível com o media query mobile)
      sidebar.classList.toggle('collapsed');
      sidebarToggle.textContent = sidebar.classList.contains('collapsed') ? '▶' : '◀';
    });
  }

  if (sidebarMobileToggle) sidebarMobileToggle.addEventListener('click', toggleSidebar);
  if (sidebarBackdrop) sidebarBackdrop.addEventListener('click', closeSidebar);
  if (sidebarOverlay) sidebarOverlay.addEventListener('click', closeSidebar);

  // ── MODULE SYSTEM: mostra só os painéis do módulo ativo ──
  // Helper puro (espelhado em tests/test_app_js_core.js): decide quais
  // abas (tab-panes) ficam ativas para um módulo. Cada módulo tem UMA aba
  // dona — sem esse mapeamento, painéis do mesmo módulo espalhados por
  // várias abas (ex.: LIVE MINING — painel principal em tab-charts,
  // terminal em tab-terminal, timeline/gráficos/logs em tab-fleet)
  // ativavam VÁRIAS abas ao mesmo tempo: página gigante com scroll
  // infinito + overflow horizontal no mobile. Módulos fora do mapa
  // mantêm o comportamento antigo (ativa TODAS as abas com painel
  // visível — a 1ª que aparecer também, sem exclusividade).
  const _MODULE_OWNED_PANES = {
    // LIVE MINING: só o painel principal (CYPHER // LIVE MINING) + o
    // terminal de comandos. Timeline/gráficos ficam fora do módulo para o
    // layout voltar a ser focado (sem scroll infinito). O LIVE LOG (#logs-
    // panel, data-module="live") vive DENTRO de #tab-terminal — painel de
    // mesmo módulo — para ficar visível aqui (era inalcançável em #tab-fleet).
    live: ['tab-charts', 'tab-terminal'],
  };
  function moduleActivePanes(name, paneHasVisible) {
    const owned = _MODULE_OWNED_PANES[name];
    if (owned) return owned.slice();
    return (paneHasVisible || []).filter(p => p.visible).map(p => p.id);
  }
  // Module navigation with exit/enter motion (design-motion-principles).
  // Exit (120ms) plays BEFORE the switch so display:none doesn't kill it;
  // ── Beta analytics: self-hosted usage tracking (Issue #353) ──
  const ANALYTICS_MIN_INTERVAL_MS = 1100;
  const _analytics = {
    _lastModule: null,
    _lastModuleTs: 0,
    _lastSentAt: 0,
    _flushTimer: 0,
    _queue: [],
  };
  function analyticsNextDelay(lastSentAt, nowMs) {
    return Math.max(0, ANALYTICS_MIN_INTERVAL_MS - (nowMs - lastSentAt));
  }
  function _sendBetaAnalytics(event, meta) {
    try {
      if (navigator.sendBeacon) {
        const blob = new Blob([JSON.stringify({ event: event, meta: meta || {} })],
          { type: 'application/json' });
        navigator.sendBeacon('/api/analytics/track', blob);
      } else {
        fetch('/api/analytics/track', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ event: event, meta: meta || {} }),
          keepalive: true,
        }).catch(function() {});
      }
    } catch(e) {}
  }
  function _flushBetaAnalytics() {
    if (!_analytics._queue.length) return;
    const delay = analyticsNextDelay(_analytics._lastSentAt, Date.now());
    if (delay > 0) {
      if (!_analytics._flushTimer) {
        _analytics._flushTimer = window.setTimeout(function() {
          _analytics._flushTimer = 0;
          _flushBetaAnalytics();
        }, delay);
      }
      return;
    }
    const next = _analytics._queue.shift();
    _analytics._lastSentAt = Date.now();
    _sendBetaAnalytics(next.event, next.meta);
    if (_analytics._queue.length) _flushBetaAnalytics();
  }
  function _betaTrack(event, meta) {
    // The server remains the abuse-control authority. This small client queue
    // avoids known-good dashboard navigation creating visible 429 responses.
    _analytics._queue.push({ event: event, meta: meta || {} });
    _flushBetaAnalytics();
  }
  function _betaTrackModuleSwitch(toMod) {
    var prev = _analytics._lastModule;
    var prevTs = _analytics._lastModuleTs;
    var now = Date.now();
    if (prev && prevTs) {
      var secs = Math.round((now - prevTs) / 1000);
      if (secs > 0 && secs < 3600) {
        _betaTrack('module_time', { module: prev, seconds: secs });
      }
    }
    _analytics._lastModule = toMod;
    _analytics._lastModuleTs = now;
    _betaTrack('module_switch', { from: prev || '(boot)', to: toMod });
  }

  // Boot event
  (function() {
    try {
      _betaTrack('boot', {
        vw: (window.innerWidth || 0) + 'x' + (window.innerHeight || 0),
        ua: navigator.userAgent ? navigator.userAgent.substring(0, 128) : '',
        ts: Date.now(),
      });
    } catch(e) {}
  })();

  // the switch is deferred by the same amount and token-guarded so rapid
  // sidebar clicks cancel the pending transition (Emil: interruptible).
  let _moduleNavToken = 0;
  function activateModule(name) {
    document.body.classList.add('module-mode');
    const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const token = ++_moduleNavToken;
    if (!reduceMotion) {
      let leavingCount = 0;
      document.querySelectorAll('[data-module].panel, [data-module].kpi-row').forEach(function(el) {
        if (el.classList.contains('sidebar__link')) return;
        const mods = (el.getAttribute('data-module') || '').split(/\s+/);
        if (mods.indexOf(name) === -1 && !el.classList.contains('module-hidden')) {
          el.classList.add('module-leave');
          leavingCount++;
        }
      });
      if (leavingCount > 0) {
        setTimeout(function() {
          if (token !== _moduleNavToken) return;  // superseded by a newer click
          _doActivateModule(name, reduceMotion);
        }, 120);
        return;
      }
    }
    _doActivateModule(name, reduceMotion);
  }
  function _doActivateModule(name, reduceMotion) {
    // Mostra/esconde cada painel com data-module — MAS nunca os links da
    // sidebar (eles também têm data-module; escondê-los quebraria a navegação)
    document.querySelectorAll('[data-module]').forEach(function(el) {
      // Links da sidebar nunca são escondidos (senão a navegação quebra)
      if (el.classList.contains('sidebar__link')) return;
      const mods = (el.getAttribute('data-module') || '').split(/\s+/);
      const show = mods.indexOf(name) !== -1;
      el.classList.toggle('module-hidden', !show);
      if (show) el.classList.remove('module-leave');
    });
    // Tab panes: apenas as abas que o módulo possui (ou, fora do mapa,
    // as que contêm painel visível) ficam ativas — nunca várias ao mesmo
    // tempo (causa do scroll infinito / overflow no Live Mining).
    const paneStates = Array.prototype.map.call(
      document.querySelectorAll('.tab-pane'),
      function(pane) {
        return {
          id: pane.id,
          visible: !!pane.querySelector('[data-module]:not(.module-hidden)'),
          el: pane,
        };
      }
    );
    const activeIds = moduleActivePanes(name, paneStates);
    paneStates.forEach(function(p) {
      p.el.classList.toggle('active', activeIds.indexOf(p.id) !== -1);
    });
    // Sidebar active state
    sidebarLinks.forEach(function(l) {
      l.classList.toggle('active', l.getAttribute('data-module') === name);
    });
    // Module header
    const info = MODULE_MAP[name] || {};
    const mhTitle = document.getElementById('module-header-title');
    const mhDesc = document.getElementById('module-header-desc');
    if (mhTitle) mhTitle.textContent = info.title || name.toUpperCase();
    if (mhDesc) mhDesc.textContent = info.desc || '';
    // Persist
    try { localStorage.setItem('_active_module', name); } catch(e) {}
    // Beta analytics: track module switch + time in previous module
    try { _betaTrackModuleSwitch(name); } catch(e) {}
    closeSidebar();
    // Depois que a visibilidade estabiliza: resize dos charts já criados
    // E cria/atualiza charts dos canvases que acabaram de ficar visíveis
    // (renderCharts pula canvases ocultos, então é seguro chamá-lo aqui)
    requestAnimationFrame(function() {
      // Motion: staggered enter for the panels that just became visible
      // (opacity + translateY + blur, 200ms, 24ms stagger — Emil <300ms).
      if (!reduceMotion) {
        let idx = 0;
        document.querySelectorAll('[data-module].panel:not(.module-hidden), [data-module].kpi-row:not(.module-hidden)').forEach(function(el) {
          el.classList.remove('module-in');
          void el.offsetWidth; // restart animation on rapid re-triggers
          el.style.setProperty('--i', String(idx++));
          el.classList.add('module-in');
          setTimeout(function() { el.classList.remove('module-in'); }, 500);
        });
      }
      Object.keys(charts).forEach(function(id) {
        const ch = charts[id];
        if (ch && typeof ch.resize === 'function') ch.resize();
      });
      if (typeof renderCharts === 'function') renderCharts();
      // Hash Market: lazy-load the 7d trend chart on first module activation.
      // On failure the flag is reset so the next activation retries.
      if (name === 'market' && !_mktTrendLoaded) {
        _mktTrendLoaded = true;
        skelShow(document.getElementById('market-panel'), 'chart');
        loadMarketTrend().then(ok => {
          skelHide(document.getElementById('market-panel'));
          if (!ok) _mktTrendLoaded = false;
        });
      }
      // Rentals: lazy-load the operator rental list on first module activation.
      if (name === 'rentals' && !_rentalsLoaded) {
        _rentalsLoaded = true;
        skelShow(document.getElementById('rentals-panel'), 'table');
        loadRentals().then(ok => {
          skelHide(document.getElementById('rentals-panel'));
          if (!ok) _rentalsLoaded = false;
        });
      }
      // Hash Market: also refresh the snapshot — the boot-time snapshot can be
      // stale (fetched before the warmup cache is hot), so the grid would open
      // with 0 offers until the next 15s poll. Same pattern as the fleet fix.
      if (name === 'admin' && typeof fetchAdminData === 'function') {
        fetchAdminData();
      }
      if (name === 'market' && typeof fetchSnapshot === 'function') {
        // Re-activation with an EMPTY grid (e.g. offers never landed): show
        // the same table skeleton until the fresh snapshot renders offers.
        const mktPanel = document.getElementById('market-panel');
        const gridEmpty = !_mktOffers || _mktOffers.length === 0;
        if (mktPanel && gridEmpty) skelShow(mktPanel, 'table');
        Promise.resolve(fetchSnapshot()).then(() => { skelHide(mktPanel); });
      }
      // Live Mining / Terminal: foca o input para digitação imediata
      if (name === 'live') {
        const termInput = document.getElementById('terminal-input');
        if (termInput) termInput.focus();
      }
      // Fleet: garante que o grid renderize imediatamente ao ativar a aba.
      // Antes o fetchAxeFleet() só rodava no poll/SSE, então a aba abria
      // com o empty-state estático mesmo com devices registrados.
      if (name === 'fleet' && typeof fetchAxeFleet === 'function') {
        const fleetPanel = document.getElementById('axe-fleet-panel');
        // Only skeleton when the grid is empty (first activation or a
        // previous fetch failed) — with devices already rendered a refresh
        // keeps them visible and skips the overlay (no flash).
        // #axe-grid starts with a static empty-state in the template, so
        // count only real device cards — with cards rendered the refresh
        // keeps them visible (no overlay flash).
        const fleetEmpty = !dom.axeGrid || !dom.axeGrid.querySelector('.axe-card, .device-card, [data-device-id]');
        if (fleetPanel && fleetEmpty) skelShow(fleetPanel, 'table');
        const _fleetP = Promise.resolve(fetchAxeFleet());
        if (typeof fetchRemoteOnboarding === 'function') fetchRemoteOnboarding();
        _fleetP.then(() => { skelHide(fleetPanel); });
      }
      // Support: abre o modal completo (manifesto + endereços) em vez de só
      // rolar até a barra compacta — o texto autoral e os endereços grandes
      // ficam no modal.
      if (name === 'support') {
        const panel = document.getElementById('support-panel');
        if (panel) {
          openModalAnimated(panel);
          renderSupportMethods();  // also fills the LN recipient row
        }
      }
    });
  }

  sidebarLinks.forEach(function(link) {
    link.addEventListener('click', function() {
      const name = link.getAttribute('data-module');
      if (name) activateModule(name);
    });
  });

  // UX audit (Quick Win): KPI cards are drill-down shortcuts to modules.
  // Clicking Total HR → Live Mining, Best Diff → Probability (Block Hunt),
  // etc. Uses event delegation so the (re-rendered) cards stay bound.
  const kpiRow = document.getElementById('kpi-row');
  if (kpiRow) {
    kpiRow.addEventListener('click', function(e) {
      const card = e.target.closest('.kpi-card[data-kpi-target]');
      if (!card) return;
      activateModule(card.getAttribute('data-kpi-target'));
    });
  }

  // P0-1: CTA do histograma de Share Difficulty → Probability (solo stats).
  // Live Mining alimenta a previsão — um clique leva ao cálculo já carregado.
  const shareDistGotoProb = document.getElementById('share-dist-goto-prob');
  if (shareDistGotoProb) {
    shareDistGotoProb.addEventListener('click', function() {
      activateModule('probability');
      const solo = document.getElementById('solo-stats-panel');
      if (solo) solo.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  }

  // UX audit (Módulo_05): WHAT-IF difficulty slider — simulate the impact of
  // a network difficulty change on P(block)/share, expected time, distance
  // and cumulative P. Pure simulation, never mutates the live snapshot.
  const bhSlider = document.getElementById('bh-whatif-slider');
  if (bhSlider) {
    bhSlider.addEventListener('input', _bhRenderWhatIf);
    const bhReset = document.getElementById('bh-whatif-reset');
    if (bhReset) {
      bhReset.addEventListener('click', function() {
        bhSlider.value = 0;
        _bhRenderWhatIf();
      });
    }
  }

  // Restore active module from localStorage on boot
  (function restoreActiveModule() {
    try {
      const saved = localStorage.getItem('_active_module');
      activateModule(saved && MODULE_MAP[saved] ? saved : 'dashboard');
    } catch(e) { activateModule('dashboard'); }
  })();

  // Close sidebar on Escape key
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && sidebar.classList.contains('open')) closeSidebar();
  });

  // Update sidebar status (called from render)
  function updateSidebarStatus(isOnline) {
    const led = document.getElementById('sidebar-led');
    const text = document.getElementById('sidebar-status-text');
    if (led) led.style.background = isOnline ? 'var(--accent-green)' : 'var(--accent-red)';
    if (text) text.textContent = isOnline ? 'ONLINE' : 'OFFLINE';
  }


  // ── Wallet-refresh gate (pure, mirrored in tests) ──
  // A snapshot is "fresh for the new wallet" when it carries the new address
  // AND has been re-polled (ts > 0). /api/set-address resets the snapshot
  // (ts=0) and forces a background poll; a brand-new wallet legitimately has
  // worker=null (pool returns 0 — a valid response, not an error), so ts is
  // the reliable "poll landed" signal — not worker presence.
  function snapshotFreshForWallet(snap, address) {
    return !!(snap &&
      String(snap.btc_address || '').toLowerCase() === String(address || '').toLowerCase() &&
      snap.ts > 0);
  }

  // ── HOTFIX v2: deterministic refresh after wallet connect ──
  // A fixed-delay fetch (1.2s) can race a slow pool API and render the
  // still-empty snapshot (ts=0), leaving the dashboard blank until the next
  // poll. The forced poll (set-address → poll_once) runs many external
  // fetches and only stamps ts at the END, so it can take 10-30s. Retry
  // every 1.5s for up to ~30s until the snapshot carries the new address
  // AND ts>0, so the dashboard lights up the moment real data lands. Give
  // up after the budget and render whatever exists — honest: the wallet IS
  // connected; data will arrive on the next scheduled poll.
  //
  // Generation guard: _walletRefreshTarget holds the LATEST wallet the user
  // asked to refresh. A retry chain that started for an older wallet stops
  // silently on its next tick (rapid A→B switching must never let the A
  // chain render B's data or a stale reset state). Only the newest chain
  // renders.
  var _walletRefreshTarget = '';
  function refreshUntilWalletReady(address, attempt) {
    _walletRefreshTarget = address;
    attempt = attempt || 0;
    fetch('/api/snapshot')
      .then(function(r) { return r.json(); })
      .then(function(snap) {
        // A newer wallet was connected — this chain is obsolete, stop now.
        if (address !== _walletRefreshTarget) return;
        if (snapshotFreshForWallet(snap, address)) {
          render(snap);
          return;
        }
        if (attempt < 20) {
          setTimeout(function() { refreshUntilWalletReady(address, attempt + 1); }, 1500);
        } else if (snap) {
          render(snap);
        }
      })
      .catch(function(err) { console.warn('[wallet-changed] refresh error:', err); });
  }

  window.addEventListener('wallet-changed', function(e) {
    var addr = e.detail && e.detail.address;
    if (addr) refreshUntilWalletReady(addr);
  });
  // The IIFE continues below — do NOT close it here!

  // ── FASE 3: Clipboard copy for donation footer ──
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('[data-copy-btn]');
    if (btn) {
      var code = btn.previousElementSibling;
      var addr = code ? code.getAttribute('data-copy') || code.textContent : '';
      if (addr && navigator.clipboard) {
        navigator.clipboard.writeText(addr).then(function() {
          var orig = btn.textContent;
          btn.textContent = '[copied]';
          setTimeout(function() { btn.textContent = orig; }, 2000);
        });
      }
    }
  });

  // ════════════════════════════════════════════════════════════════════════
  // INSTITUTIONAL DASHBOARD · UI CONTROLLER
  // ════════════════════════════════════════════════════════════════════════
  const InstitutionalUI = {
    init: function() {
      this.bindTabs();
      this.bindAIOperator();
    },
    bindTabs: function() {
      var tabBtns = document.querySelectorAll('.tab-btn');
      var tabPanes = document.querySelectorAll('.tab-pane');
      if (!tabBtns.length) return;
      tabBtns.forEach(function(btn) {
        btn.addEventListener('click', function(e) {
          var targetId = e.currentTarget.getAttribute('data-target');
          var targetPane = document.getElementById(targetId);
          if (!targetPane) return;
          tabBtns.forEach(function(b) { b.classList.remove('active'); });
          tabPanes.forEach(function(p) { p.classList.remove('active'); });
          e.currentTarget.classList.add('active');
          targetPane.classList.add('active');
          // When Deep Analytics tab is clicked, resize charts
          // (canvases have display:none; Chart.js can't measure them)
          // requestAnimationFrame ensures browser computed layout after display:block
          if (targetId === 'tab-charts' && typeof charts !== 'undefined') {
            requestAnimationFrame(function() {
              Object.values(charts).forEach(function(ch) {
                if (ch && typeof ch.resize === 'function') ch.resize();
              });
            });
          }
        });
      });
    },
    bindAIOperator: function() {
      var aiToggleBtn = document.getElementById('sidebar-toggle');
      var aiPanel = document.getElementById('ai-operator-panel');
      if (!aiToggleBtn || !aiPanel) return;
      aiToggleBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        aiPanel.classList.toggle('active');
      });
      document.addEventListener('click', function(e) {
        if (aiPanel.classList.contains('active') && !aiPanel.contains(e.target) && !aiToggleBtn.contains(e.target)) {
          aiPanel.classList.remove('active');
        }
      });
    }
  };

  // ── Initialize Institutional UI after DOM ready ──
  if (document.readyState !== 'loading') {
    InstitutionalUI.init();
  } else {
    document.addEventListener('DOMContentLoaded', function() { InstitutionalUI.init(); });
  }

  // ════════════════════════════════════════════════════════════════════════
  // INSTITUTIONAL DASHBOARD · CORE DATA BINDER
  // ════════════════════════════════════════════════════════════════════════
  var DashboardCore = {
    renderSnapshot: function(snap) {
      if (!snap) return;
      this.updateTopbar(snap.network, snap.mempool_fees, snap.btc_price, snap.alerts_recent);
      this.updateCommandCenter(snap.worker, snap.axe_fleet, snap.pool, snap.profitability);
      this.updateRadar(snap.proximity, snap.worker);
      this.setSystemStatus('online');
    },
    setText: function(id, text) {
      var el = document.getElementById(id);
      if (el) el.textContent = text || '\u2014';
    },
    setSystemStatus: function(status) {
      var pill = document.getElementById('status-pill');
      if (pill) { pill.className = 'status-indicator ' + status; }
    },
    formatHashrate: function(hs) {
      if (!hs) return '0 H/s';
      if (hs > 1e18) return (hs / 1e18).toFixed(2) + ' EH/s';
      if (hs > 1e15) return (hs / 1e15).toFixed(2) + ' PH/s';
      if (hs > 1e12) return (hs / 1e12).toFixed(2) + ' TH/s';
      if (hs > 1e9) return (hs / 1e9).toFixed(2) + ' GH/s';
      return Number(hs).toLocaleString() + ' H/s';
    },
    updateTopbar: function(net, fees, btc, alerts) {
      var btcPrice = btc && btc.usd ? '$' + Number(btc.usd).toLocaleString() : '--';
      this.setText('n-btc-usd', btcPrice);
      this.setText('n-diff', net ? this.formatHashrate(net.difficulty) : '--');
      this.setText('n-hashrate', net ? this.formatHashrate(net.hashrate) : '--');
      this.setText('n-height', net && net.height ? '#' + net.height : '--');
      this.setText('fee-fastest', fees && fees.fastestFee != null ? fees.fastestFee + ' sat/vB' : '--');
      var alertBadge = document.getElementById('alerts-count-badge');
      if (alertBadge && alerts) {
        alertBadge.textContent = alerts.length;
        alertBadge.style.display = alerts.length > 0 ? 'inline-block' : 'none';
      }
    },
    updateCommandCenter: function(worker, fleet, pool, profit) {
      // Issue #51 (audit): do NOT setText on #hero-worker — that id is the
      // WHOLE panel section, so el.textContent wipes every child metric
      // (m-hashrate, m-state, hc-*, hero grid). The hero values are owned by
      // renderHero()/renderHostCore() (called by the original render).
      // p-hashrate, p-workers handled by renderPool() — do not duplicate
      this.setText('p-high-diff', pool ? String(pool.highestDifficulty || '--') : '--');
      this.setText('hc-network', pool ? String(pool.hashrate || '--') : '--');
      if (profit) {
        this.setText('p-btc-day', profit.net_btc_per_day_pool != null ? profit.net_btc_per_day_pool.toFixed(6) + ' BTC' : '--');
        var fiatDay = profit.fiat_per_day_pool ? profit.fiat_per_day_pool.USD : null;
        this.setText('p-fiat-day', fiatDay != null ? '$' + Number(fiatDay).toLocaleString(undefined, {maximumFractionDigits: 0}) : '--');
      }
    },
    updateRadar: function(prox, worker) {
      if (prox) {
        this.setText('prox-hero-pct', prox.pct_of_network_cur != null ? prox.pct_of_network_cur.toFixed(4) + '%' : '--');
        this.setText('prox-chance', prox.chance_per_share_label || '--');
        this.setText('prox-time', prox.expected_time_human || '--');
        this.setText('bh-distance', prox.distance_label || '--');
        this.setText('bh-p-block', prox.chance_per_share_pct != null ? (Number(prox.chance_per_share_pct) * 100).toFixed(6) + '%' : '--');
      }
      this.setText('prox-hero-best', prox && prox.all_time_best_diff_str ? 'best ' + prox.all_time_best_diff_str : '--');
      this.setText('hunt-metrics-bestdiff', worker && worker.bestDifficulty ? String(worker.bestDifficulty) : '--');
    },
  };

  // ── Extend existing InstitutionalUI to also handle off-canvas AI panel ──
  if (typeof InstitutionalUI !== 'undefined' && InstitutionalUI) {
    var _origBindAI = InstitutionalUI.bindAIOperator;
    InstitutionalUI.bindAIOperator = function() {
      // Call original binding for inline ai-operator-panel
      if (_origBindAI) _origBindAI.call(this);

      // Also bind off-canvas-ai panel — a DEDICATED trigger (#ai-panel-toggle),
      // never the #sidebar-toggle: reusing the sidebar button made the
      // off-canvas panel (z-index 500) cover the ☰ button when both opened,
      // so the second click never reached the sidebar toggle and the sidebar
      // stayed stuck open (E2E topbar-responsive caught it). The AI panel
      // keeps its own close button and outside-click dismiss.
      var toggleBtn = document.getElementById('ai-panel-toggle');
      var panel = document.getElementById('off-canvas-ai');
      var closeBtn = document.getElementById('off-canvas-ai-close');
      if (!toggleBtn || !panel) return;
      toggleBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        panel.classList.toggle('active');
      });
      if (closeBtn) {
        closeBtn.addEventListener('click', function() {
          panel.classList.remove('active');
        });
      }
      document.addEventListener('click', function(e) {
        if (panel.classList.contains('active') && !panel.contains(e.target) && !toggleBtn.contains(e.target)) {
          panel.classList.remove('active');
        }
      });
    };

    // Note: init() is called by existing DOMContentLoaded listener
    // (which fires after this sync extension, so the overridden methods are active)
  }    // ── Wire DashboardCore into the existing render cycle ──
    var _origRender = render;
    render = function(snap) {
      _origRender(snap);
      DashboardCore.renderSnapshot(snap);
      renderKpiCards(snap);
    };

    // NOTE (dom-scope fix): the main IIFE opened at the top of this file must
    // close at the very END of the file. Previously a stray `})();` here closed
    // the IIFE early, pushing renderKpiCards() and everything below into GLOBAL
    // scope where `dom` (a const inside the IIFE) does not exist — every render
    // threw "ReferenceError: dom is not defined" (throttled to ~5/min in the
    // LIVE LOG). The IIFE now continues to the file's last line.

  // ── Sidebar collapse toggle ──
  document.getElementById('sidebar-collapse')?.addEventListener('click', function() {
    document.getElementById('sidebar')?.classList.toggle('collapsed');
    var btn = document.getElementById('sidebar-collapse');
    if (btn) btn.textContent = document.getElementById('sidebar')?.classList.contains('collapsed') ? '▶' : '◀';
  });

  // ── Docs: IntersectionObserver for active section ──
  var _docsObserver = null;
  var _docsSearchInitialized = false;
  function _initDocsObserver() {
    if (_docsObserver) return;
    // Scoped to the docs container: the LEARNING panel also uses .doc-section
    // markup (whitepaper/library) but must NOT feed the docs active-link
    // highlight — otherwise its sections would steal the observer's focus.
    var docsContainer = document.querySelector('.docs-container');
    var sections = docsContainer ? docsContainer.querySelectorAll('.doc-section') : [];
    if (!sections.length) return;
    var links = document.querySelectorAll('.docs-index__link');
    _docsObserver = new IntersectionObserver(function(entries) {
      var visible = [];
      entries.forEach(function(entry) {
        if (entry.isIntersecting) visible.push(entry.target.id);
      });
      if (!visible.length) return;
      var topId = visible.reduce(function(a, b) {
        var elA = document.getElementById(a), elB = document.getElementById(b);
        return (elA && elA.getBoundingClientRect().top || 0) < (elB && elB.getBoundingClientRect().top || 0) ? a : b;
      });
      links.forEach(function(link) {
        link.classList.toggle('docs-index__link--active', link.getAttribute('data-section') === topId);
      });
    }, { rootMargin: '-80px 0px -60% 0px', threshold: 0 });
    sections.forEach(function(s) { _docsObserver.observe(s); });
  }

  // ── Docs: Search / filter + AUTOCOMPLETE (UX audit · Módulo_09) ──
  // Pure helpers below (docsBuildIndex/docsSearchSuggestions/docsSnippet/
  // docsHighlight) are mirrored in tests/test_app_js_core.js (SUITE 34).
  var _docsIndex = [];       // built once from the .docs-container sections
  var _docsSuggestions = []; // current autocomplete results
  var _docsActive = -1;      // keyboard cursor into _docsSuggestions

  // Build the search index from the docs container (scoped — the LEARNING
  // panel reuses .doc-section markup and must NOT pollute the docs index).
  function docsBuildIndex() {
    var container = document.querySelector('.docs-container');
    if (!container) return [];
    var sections = container.querySelectorAll('.doc-section');
    var idx = [];
    sections.forEach(function(sec) {
      var titleEl = sec.querySelector('.doc-section__title');
      idx.push({
        id: sec.id || '',
        title: titleEl ? titleEl.textContent.trim() : '',
        text: (sec.textContent || '').trim(),
      });
    });
    return idx;
  }

  // Pure: rank sections by query relevance. Title hits rank far above body
  // hits; earlier positions beat later ones. Returns up to `limit` entries
  // as {id, title, snippet} where snippet is a text window around the hit.
  function docsSearchSuggestions(index, q, limit) {
    limit = limit || 6;
    q = String(q || '').trim().toLowerCase();
    if (!q || !index.length) return [];
    var scored = [];
    index.forEach(function(sec) {
      var titleLow = (sec.title || '').toLowerCase();
      var textLow = (sec.text || '').toLowerCase();
      var titleIdx = titleLow.indexOf(q);
      var textIdx = textLow.indexOf(q);
      if (titleIdx === -1 && textIdx === -1) return;
      var score = titleIdx !== -1 ? 100 - titleIdx : 40 - Math.min(textIdx, 40);
      scored.push({ sec: sec, score: score, titleIdx: titleIdx, textIdx: textIdx });
    });
    scored.sort(function(a, b) { return b.score - a.score; });
    return scored.slice(0, limit).map(function(item) {
      var pos = item.titleIdx !== -1 ? Math.max(0, item.titleIdx) : Math.max(0, item.textIdx);
      return {
        id: item.sec.id,
        title: item.sec.title,
        snippet: docsSnippet(item.sec.text, q, pos),
      };
    });
  }

  // Pure: a text window of ±radius chars around `pos`, collapsing whitespace.
  function docsSnippet(text, q, pos, radius) {
    radius = radius || 60;
    var t = String(text || '').replace(/\s+/g, ' ');
    q = String(q || '');
    var start = Math.max(0, pos - radius);
    var end = Math.min(t.length, pos + q.length + radius);
    var snippet = t.slice(start, end);
    if (start > 0) snippet = '\u2026' + snippet;
    if (end < t.length) snippet = snippet + '\u2026';
    return snippet;
  }

  // Pure: escape text and wrap every case-insensitive occurrence of `q` in
  // <mark> for visual highlight inside the suggestion item.
  function docsHighlight(text, q) {
    var t = String(text || '');
    var needle = String(q || '').trim();
    if (!needle) return escapeHtml(t);
    var lower = t.toLowerCase();
    var nl = needle.toLowerCase();
    var out = '';
    var i = 0;
    while (i < t.length) {
      var hit = lower.indexOf(nl, i);
      if (hit === -1) { out += escapeHtml(t.slice(i)); break; }
      out += escapeHtml(t.slice(i, hit));
      out += '<mark>' + escapeHtml(t.slice(hit, hit + needle.length)) + '</mark>';
      i = hit + needle.length;
    }
    return out;
  }

  // ── Learning FAQ loop (Issue #19) — 'was this helpful?' widget ───────
  // Pure helpers below (docsFeedbackPct/docsFeedbackSectionLabel) are
  // mirrored in tests/test_app_js_core.js (SUITE 35).
  function docsFeedbackPct(helpful, total) {
    if (!total) return null;  // honest — no votes, no fabricated %
    return Math.round(helpful / total * 1000) / 10;
  }
  function docsFeedbackSectionLabel(sectionId) {
    const m = String(sectionId || '').match(/^docs[-_](.+)$/);
    return m ? m[1].replace(/[-_]/g, ' ') : String(sectionId || '—');
  }

  var _docsFeedbackState = {};      // section_id -> {helpful, voted}
  var _docsFeedbackInitialized = false;

  function _initDocsFeedback() {
    if (_docsFeedbackInitialized) return;
    const container = document.querySelector('.docs-container');
    if (!container) return;
    const sections = container.querySelectorAll('.doc-section');
    if (!sections.length) return;
    _docsFeedbackInitialized = true;

    sections.forEach(function(sec) {
      const id = sec.id;
      if (!id || sec.querySelector('.doc-feedback')) return;
      const widget = document.createElement('div');
      widget.className = 'doc-feedback';
      widget.setAttribute('data-section', id);
      widget.innerHTML =
        '<span class="doc-feedback__ask">Was this section helpful?</span>' +
        '<button type="button" class="doc-feedback__btn doc-feedback__btn--yes" data-helpful="1" title="Yes — it helped">' + _ic('thumbsUp', 12, true) + 'Yes</button>' +
        '<button type="button" class="doc-feedback__btn doc-feedback__btn--no" data-helpful="0" title="No — could be better">' + _ic('thumbsDown', 12, true) + 'No</button>' +
        '<span class="doc-feedback__state" aria-live="polite"></span>' +
        '<div class="doc-feedback__comment" hidden>' +
        '  <textarea class="doc-feedback__textarea" rows="2" maxlength="500" placeholder="What were you looking for? (feeds the FAQ loop)"></textarea>' +
        '  <button type="button" class="doc-feedback__send">Send</button>' +
        '</div>';
      sec.appendChild(widget);
      _bindDocFeedbackWidget(widget, id);
    });

    // Restore the current tenant's votes so thumbs stay across module switches.
    authFetch('/api/docs/feedback').then(function(r) {
      if (!r.ok) return;
      return r.json();
    }).then(function(data) {
      (data && data.votes || []).forEach(function(v) {
        if (!v || !v.section_id) return;
        // The GET was issued before any POST — skip sections the user already
        // voted on locally so a stale restore never reverts a fresh vote.
        if (_docsFeedbackState[v.section_id]) return;
        _docsFeedbackState[v.section_id] = { helpful: !!v.helpful, voted: true };
        const w = container.querySelector('.doc-feedback[data-section="' + v.section_id + '"]');
        if (w) _docsFeedbackSetState(w, v.section_id, !!v.helpful, '');
      });
    }).catch(function() { /* offline — votes stay local */ });
  }

  function _bindDocFeedbackWidget(widget, sectionId) {
    const yesBtn = widget.querySelector('.doc-feedback__btn--yes');
    const noBtn = widget.querySelector('.doc-feedback__btn--no');
    const commentWrap = widget.querySelector('.doc-feedback__comment');
    const textarea = widget.querySelector('.doc-feedback__textarea');
    const sendBtn = widget.querySelector('.doc-feedback__send');

    yesBtn.addEventListener('click', function() {
      if (_docsFeedbackState[sectionId] && _docsFeedbackState[sectionId].voted) return;
      commentWrap.hidden = true;
      _docsFeedbackVote(sectionId, true, widget, '');
    });
    noBtn.addEventListener('click', function() {
      if (_docsFeedbackState[sectionId] && _docsFeedbackState[sectionId].voted) return;
      commentWrap.hidden = false;
      textarea.focus();
    });
    sendBtn.addEventListener('click', function() {
      if (_docsFeedbackState[sectionId] && _docsFeedbackState[sectionId].voted) return;
      const comment = textarea.value.trim();
      _docsFeedbackVote(sectionId, false, widget, comment);
    });
  }

  function _docsFeedbackVote(sectionId, helpful, widget, comment) {
    const stateEl = widget.querySelector('.doc-feedback__state');
    authFetch('/api/docs/feedback', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ section_id: sectionId, helpful: helpful, comment: comment })
    }).then(function(r) {
      if (!r.ok) { stateEl.textContent = 'could not save — try again'; return; }
      _docsFeedbackState[sectionId] = { helpful: helpful, voted: true };
      _docsFeedbackSetState(widget, sectionId, helpful, comment);
    }).catch(function() {
      stateEl.textContent = 'offline — not saved';
    });
  }

  function _docsFeedbackSetState(widget, sectionId, helpful, comment) {
    const yesBtn = widget.querySelector('.doc-feedback__btn--yes');
    const noBtn = widget.querySelector('.doc-feedback__btn--no');
    const stateEl = widget.querySelector('.doc-feedback__state');
    const commentWrap = widget.querySelector('.doc-feedback__comment');
    yesBtn.classList.toggle('is-active', !!helpful);
    noBtn.classList.toggle('is-active', !helpful);
    yesBtn.disabled = true;
    noBtn.disabled = true;
    stateEl.textContent = helpful
      ? 'Thanks — glad it helped ✓'
      : (comment ? 'Thanks — we\'ll improve this section' : 'Thanks — feedback recorded');
    commentWrap.hidden = true;
  }

  function _docsCloseSuggestions() {
    var box = document.getElementById('docs-search-suggestions');
    var input = document.getElementById('docs-search-input');
    if (box) { box.innerHTML = ''; box.classList.remove('open'); }
    if (input) input.setAttribute('aria-expanded', 'false');
    _docsSuggestions = [];
    _docsActive = -1;
  }

  function _docsGoTo(id) {
    var el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    var links = document.querySelectorAll('.docs-index__link');
    links.forEach(function(link) {
      link.classList.toggle('docs-index__link--active', link.getAttribute('data-section') === id);
    });
    _docsCloseSuggestions();
  }

  // Render the autocomplete dropdown for the current query. Empty query or
  // no matches produce an honest empty state instead of stale suggestions.
  function _docsRenderSuggestions(q) {
    var box = document.getElementById('docs-search-suggestions');
    var input = document.getElementById('docs-search-input');
    if (!box || !input) return;
    if (!q) { _docsCloseSuggestions(); return; }
    _docsSuggestions = docsSearchSuggestions(_docsIndex, q, 6);
    if (!_docsSuggestions.length) {
      box.innerHTML = '<div class="docs-search__empty">no matches for \u201c' + escapeHtml(q) + '\u201d</div>';
      box.classList.add('open');
      input.setAttribute('aria-expanded', 'true');
      return;
    }
    box.innerHTML = _docsSuggestions.map(function(s, i) {
      return '<button type="button" class="docs-search__item' + (i === _docsActive ? ' active' : '') + '" data-docs-id="' + escapeHtml(s.id) + '" role="option" aria-selected="' + (i === _docsActive) + '">' +
        '<span class="docs-search__item-title">' + docsHighlight(s.title, q) + '</span>' +
        '<span class="docs-search__item-snippet">' + docsHighlight(s.snippet, q) + '</span>' +
        '</button>';
    }).join('');
    box.classList.add('open');
    input.setAttribute('aria-expanded', 'true');
  }

  function _initDocsSearch() {
    if (_docsSearchInitialized) return;
    var input = document.getElementById('docs-search-input');
    var clear = document.getElementById('docs-search-clear');
    var box = document.getElementById('docs-search-suggestions');
    var links = document.querySelectorAll('.docs-index__links .docs-index__link');
    if (!input || !links.length) return;
    _docsSearchInitialized = true;
    _docsIndex = docsBuildIndex();

    input.addEventListener('input', function() {
      var q = this.value.trim().toLowerCase();
      _docsActive = -1;  // reset the keyboard cursor on a new query
      _docsRenderSuggestions(q);
      links.forEach(function(link) {
        var section = document.getElementById(link.getAttribute('data-section'));
        if (!section) return;
        if (!q) {
          section.style.display = '';
          link.style.display = '';
        } else {
          var match = section.textContent.toLowerCase().indexOf(q) !== -1;
          section.style.display = match ? '' : 'none';
          link.style.display = match ? '' : 'none';
        }
      });
      // `block` (not '' — an empty string would remove the inline style and
      // restore the stylesheet's `display:none`, keeping the ✕ button forever
      // invisible; found by the docs-autocomplete E2E).
      if (clear) clear.style.display = q ? 'block' : 'none';
    });

    // Keyboard: ↑/↓ move the cursor, Enter opens the selected section,
    // Escape closes the dropdown.
    input.addEventListener('keydown', function(e) {
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        if (!_docsSuggestions.length) return;
        var step = e.key === 'ArrowDown' ? 1 : -1;
        _docsActive = Math.max(0, Math.min(_docsSuggestions.length - 1, _docsActive + step));
        _docsRenderSuggestions(this.value.trim().toLowerCase());
      } else if (e.key === 'Enter') {
        if (_docsActive >= 0 && _docsSuggestions[_docsActive]) {
          e.preventDefault();
          _docsGoTo(_docsSuggestions[_docsActive].id);
        }
      } else if (e.key === 'Escape') {
        _docsCloseSuggestions();
      }
    });

    // mousedown (not click) so the blur handler below never beats it — the
    // suggestion fires before the input loses focus.
    if (box) {
      box.addEventListener('mousedown', function(e) {
        var item = e.target.closest('.docs-search__item');
        if (item) { e.preventDefault(); _docsGoTo(item.getAttribute('data-docs-id')); }
      });
      // Hover moves the keyboard cursor for Enter-to-open consistency.
      box.addEventListener('mouseover', function(e) {
        var item = e.target.closest('.docs-search__item');
        if (!item) return;
        _docsActive = Array.prototype.indexOf.call(box.children, item);
        var items = box.querySelectorAll('.docs-search__item');
        items.forEach(function(el, i) { el.classList.toggle('active', i === _docsActive); });
      });
    }

    input.addEventListener('blur', function() {
      setTimeout(_docsCloseSuggestions, 120);
    });

    clear?.addEventListener('click', function() {
      input.value = '';
      input.dispatchEvent(new Event('input', { bubbles: true }));
      input.focus();
    });
  }

  // Initialize docs features once at boot if the section exists
  if (document.getElementById('section-docs')) {
    // Use requestIdleCallback or on first scroll to not block initial render
    var _initDocs = function() {
      _initDocsObserver();
      _initDocsSearch();
      _initDocsFeedback();
    };
    if (window.requestIdleCallback) {
      requestIdleCallback(_initDocs, { timeout: 2000 });
    } else {
      setTimeout(_initDocs, 1500);
    }
  }

  // ── Collapsible FAQ ──
  document.addEventListener('click', function(e) {
    var faqQ = e.target.closest('.doc-faq-item__q');
    if (faqQ) {
      var answer = faqQ.nextElementSibling;
      if (answer && answer.classList.contains('doc-faq-item__a')) {
        if (answer.style.display === 'none') {
          answer.style.display = '';
          faqQ.classList.remove('doc-faq-item__q--collapsed');
        } else {
          answer.style.display = 'none';
          faqQ.classList.add('doc-faq-item__q--collapsed');
        }
      }
    }
  });

  // ── Sidebar module navigation — implemented via activateModule() above ──
  // (SECTION_MAP removido — a navegação agora usa data-module)

  // ── Collapsible panels toggle ──
  document.addEventListener('click', function(e) {
    var toggle = e.target.closest('.panel__toggle');
    if (!toggle) return;
    var panel = toggle.closest('.panel--collapsible');
    if (!panel) return;
    panel.classList.toggle('collapsed');
    toggle.classList.toggle('collapsed');
  });

  // ── KPI Cards render ──
  function renderKpiCards(snap) {
    if (!snap) return;
    var w = snap.worker || {};
    var pool = snap.pool || {};
    var prox = snap.proximity || {};
    var workers = snap.all_workers || [];

    if (dom.kpiHashrate) dom.kpiHashrate.textContent = fmt.hashrate(w.hashrate);
    if (dom.kpiBestdiff) dom.kpiBestdiff.textContent = fmt.diff(w.bestDifficulty || w.best_diff);
    if (dom.kpiPoolhr) dom.kpiPoolhr.textContent = fmt.hashrate(pool.hashrate);

    // Share rate — from active workers or timeline
    if (dom.kpiShares) {
      var sharesCount = prox.live_calc?.session_totals?.shares_so_far || 0;
      var shareRate = prox.share_rate_hourly || 0;
      if (shareRate > 0) {
        dom.kpiShares.textContent = shareRate.toFixed(0) + '/h';
      } else if (sharesCount > 0) {
        dom.kpiShares.textContent = sharesCount + ' total';
      } else {
        dom.kpiShares.textContent = '\u2014';
      }
    }
  }

  // ── Close the main IIFE (opened at the top of the file) ──
  // The renderKpiCards() helper and every handler above live INSIDE this scope
  // so `dom`, `fmt`, etc. resolve correctly. Do not add code after this line.
