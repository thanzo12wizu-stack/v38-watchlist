#!/usr/bin/env node

import { createCipheriv, createDecipheriv, pbkdf2Sync, randomBytes } from 'node:crypto';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { dirname } from 'node:path';

const VERSION = 1;
const ITERATIONS = 310000;
const KEY_BYTES = 32;
const IV_BYTES = 12;
const SALT_BYTES = 16;

function passphrase() {
  const value = String(process.env.V38_PRIVATE_DASHBOARD_PASSPHRASE || '');
  if (value.length < 12) {
    throw new Error('V38_PRIVATE_DASHBOARD_PASSPHRASE must contain at least 12 characters');
  }
  return value;
}

function encryptBuffer(input) {
  const salt = randomBytes(SALT_BYTES);
  const iv = randomBytes(IV_BYTES);
  const key = pbkdf2Sync(passphrase(), salt, ITERATIONS, KEY_BYTES, 'sha256');
  const cipher = createCipheriv('aes-256-gcm', key, iv);
  const encrypted = Buffer.concat([cipher.update(input), cipher.final()]);
  const tag = cipher.getAuthTag();
  return {
    version: VERSION,
    cipher: 'AES-256-GCM',
    kdf: 'PBKDF2-SHA256',
    iterations: ITERATIONS,
    salt: salt.toString('base64'),
    iv: iv.toString('base64'),
    ciphertext: Buffer.concat([encrypted, tag]).toString('base64'),
  };
}

function decryptBuffer(envelope) {
  if (Number(envelope.version) !== VERSION) {
    throw new Error(`unsupported private bundle version: ${envelope.version}`);
  }
  const salt = Buffer.from(envelope.salt, 'base64');
  const iv = Buffer.from(envelope.iv, 'base64');
  const combined = Buffer.from(envelope.ciphertext, 'base64');
  if (combined.length < 17) throw new Error('invalid ciphertext');
  const encrypted = combined.subarray(0, combined.length - 16);
  const tag = combined.subarray(combined.length - 16);
  const key = pbkdf2Sync(passphrase(), salt, Number(envelope.iterations), KEY_BYTES, 'sha256');
  const decipher = createDecipheriv('aes-256-gcm', key, iv);
  decipher.setAuthTag(tag);
  return Buffer.concat([decipher.update(encrypted), decipher.final()]);
}

function ensureParent(path) {
  mkdirSync(dirname(path), { recursive: true });
}

function lockedHtml(envelope) {
  const payload = JSON.stringify(envelope).replaceAll('<', '\\u003c');
  return `<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><meta name="robots" content="noindex,nofollow"><meta name="theme-color" content="#080c11"><title>V38 Private Intelligence</title><style>
:root{color-scheme:dark;--bg:#080c11;--panel:#111821;--line:#293545;--text:#f2f6fb;--muted:#94a2b5;--accent:#78afff;--bad:#ff7373}*{box-sizing:border-box}body{margin:0;min-height:100svh;background:radial-gradient(circle at 20% 0,rgba(120,175,255,.14),transparent 35%),var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:520px;margin:auto;padding:max(42px,env(safe-area-inset-top)) 18px}.card{margin-top:18vh;background:var(--panel);border:1px solid var(--line);border-radius:18px;padding:20px}h1{font-size:24px;margin:0}.muted{color:var(--muted);font-size:13px;line-height:1.55;margin:8px 0 18px}label{display:block;color:var(--muted);font-size:12px;margin-bottom:6px}input{width:100%;min-height:48px;border:1px solid var(--line);border-radius:11px;background:#080c11;color:var(--text);padding:10px 12px;font-size:16px}button{width:100%;min-height:48px;margin-top:10px;border:0;border-radius:11px;background:var(--accent);color:#07101d;font-weight:800;font-size:15px}.error{color:var(--bad);font-size:12px;min-height:18px;margin-top:9px}.home{display:block;color:var(--accent);text-decoration:none;font-size:12px;margin-top:14px;text-align:center}</style></head><body><div class="wrap"><div class="card"><h1>V38 Private Intelligence</h1><p class="muted">詳細データは端末内で復号されます。パスフレーズはサーバーへ送信されません。</p><form id="unlock"><label for="password">パスフレーズ</label><input id="password" type="password" autocomplete="current-password" required><button type="submit">ダッシュボードを開く</button><div id="error" class="error"></div></form><a class="home" href="index.html">← Command Hub</a></div></div><script>
const bundle=${payload};
const bytes=b64=>Uint8Array.from(atob(b64),c=>c.charCodeAt(0));
document.getElementById('unlock').addEventListener('submit',async event=>{event.preventDefault();const error=document.getElementById('error');error.textContent='復号中…';try{const password=new TextEncoder().encode(document.getElementById('password').value);const base=await crypto.subtle.importKey('raw',password,'PBKDF2',false,['deriveKey']);const key=await crypto.subtle.deriveKey({name:'PBKDF2',salt:bytes(bundle.salt),iterations:bundle.iterations,hash:'SHA-256'},base,{name:'AES-GCM',length:256},false,['decrypt']);const plain=await crypto.subtle.decrypt({name:'AES-GCM',iv:bytes(bundle.iv)},key,bytes(bundle.ciphertext));const text=new TextDecoder().decode(plain);document.open();document.write(text);document.close()}catch(e){error.textContent='パスフレーズが違うか、暗号化データが破損しています。'}});
</script></body></html>`;
}

function placeholderHtml() {
  return `<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>V38 Private Intelligence</title><style>:root{color-scheme:dark}body{margin:0;background:#080c11;color:#f2f6fb;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}.wrap{max-width:540px;margin:20vh auto;padding:20px}.card{background:#111821;border:1px solid #293545;border-radius:16px;padding:20px}p{color:#94a2b5;line-height:1.6}a{color:#78afff}</style></head><body><div class="wrap"><div class="card"><h1>Private Dashboard Locked</h1><p>暗号化用Secretが未設定のため、詳細データは公開していません。GitHub ActionsのSecretに <code>V38_PRIVATE_DASHBOARD_PASSPHRASE</code> を設定して再実行してください。</p><a href="index.html">← Command Hub</a></div></div></body></html>`;
}

const [mode, inputPath, outputPath] = process.argv.slice(2);
if (!mode || !outputPath) {
  console.error('usage: private_crypto.mjs <encrypt|decrypt|lock-html|placeholder-html> [input] <output>');
  process.exit(2);
}

try {
  if (mode === 'encrypt') {
    const envelope = encryptBuffer(readFileSync(inputPath));
    ensureParent(outputPath);
    writeFileSync(outputPath, JSON.stringify(envelope));
  } else if (mode === 'decrypt') {
    const envelope = JSON.parse(readFileSync(inputPath, 'utf8'));
    ensureParent(outputPath);
    writeFileSync(outputPath, decryptBuffer(envelope));
  } else if (mode === 'lock-html') {
    const envelope = encryptBuffer(readFileSync(inputPath));
    ensureParent(outputPath);
    writeFileSync(outputPath, lockedHtml(envelope));
  } else if (mode === 'placeholder-html') {
    ensureParent(outputPath);
    writeFileSync(outputPath, placeholderHtml());
  } else {
    throw new Error(`unknown mode: ${mode}`);
  }
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
