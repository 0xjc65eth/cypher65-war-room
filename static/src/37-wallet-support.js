  // ══════════════════════════════════════════════════════════════════════
  // WALLET + SUPPORT — R3 + R20 do RFC 478 (Issue 551 · PR 9)
  // ══════════════════════════════════════════════════════════════════════
  // Blocos movidos VERBATIM de static/src/40-app-logic.js (sem reindentar,
  // sem reescrever comentário, sem "aproveitar para limpar"):
  //   · R3  44–642   (599 linhas) Wallet crypto — WebLN, bech32, validação
  //                  de endereço, gerador de QR (buildQrMath/QrPoly/qrEncode/
  //                  qrSvg) e identidade/health da wallet.
  //   · R20 2599–3031 (433 linhas) Support — doações, LN (sendLNPayment),
  //                  modal/histórico da wallet.
  //
  // ── POR QUE ESTE FRAGMENTO VEM ANTES DO `40-app-logic.js` ──────────────
  // As 18 statements de topo do domínio (renderSupportMethods(), loadDonations(),
  // toggleWalletCTA(), QrPoly.prototype.*, o IIFE buildQrMath e os listeners de
  // wallet) executam DURANTE a avaliação do fragmento. No arquivo original elas
  // rodavam ANTES do `boot();` (linha 3260 do god file). Se este fragmento
  // viesse depois do 40, elas rodariam DEPOIS do boot — inversão de ordem
  // silenciosa. Antes do 40, a ordem relativa é preservada (mesmo raciocínio do
  // 38-billing-auth.js e do 39-terminal.js).
  //
  // Dependências das statements de topo resolvem por HOISTING (`escapeHtml`,
  // `cssVar`, `openModalAnimated`, `authFetch` são function declarations dentro
  // do IIFE único) ou por fragmento ANTERIOR (`dom` é `const` no
  // 20-dom-primitives.js). Nenhuma lê `const`/`let` definido depois.
  //
  // Divergências do recorte verbatim em relação ao god file: o `dom.walletSave`
  // (linha 2928) já estava em COLUNA 0 no original — preservado assim, de
  // propósito, para não inflar o diff e manter a prova de permutação.
  // ══════════════════════════════════════════════════════════════════════

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

