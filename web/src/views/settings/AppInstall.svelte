<script>
  // Einstellungen › Als App nutzen: as little as possible for the user to do. Installs with
  // one button where the browser lets it (Chromium on HTTPS), else the steps for exactly this
  // device and browser; from a computer a QR code takes the app to the phone; the addresses
  // to copy (Android often does not find "aroio.local", the IP address always works).
  import { Copy, Download, Smartphone, SquareCheck } from '@lucide/svelte';
  import PageHeader from '../../components/PageHeader.svelte';
  import InstallGuide from '../../components/InstallGuide.svelte';
  import Segmented from '../../components/Segmented.svelte';
  import { app, toast } from '../../lib/state.svelte.js';
  import { installed, mobile } from '../../lib/platform.js';
  import { t } from '../../lib/i18n.svelte.js';

  const n = $derived(app.topics.network);
  const port = typeof location !== 'undefined' && location.port ? `:${location.port}` : '';
  const addresses = $derived([
    { label: t('Name im Heimnetz'), url: `http://${n?.hostname || 'aroio'}.local${port}` },
    ...(n?.lan?.address ? [{ label: t('IP-Adresse (Kabel)'), url: `http://${n.lan.address}${port}` }] : []),
    ...(n?.wifi?.address ? [{ label: t('IP-Adresse (WLAN)'), url: `http://${n.wifi.address}${port}` }] : []),
  ]);
  let qrWhich = $state(0);
  let qrFailed = $state(false);
  const qrUrl = $derived(addresses[Math.min(qrWhich, addresses.length - 1)]?.url);

  async function install() {
    const prompt = app.installPrompt;
    if (!prompt) return;
    prompt.prompt();
    const { outcome } = await prompt.userChoice;
    if (outcome === 'accepted') { app.installPrompt = null; toast(t('Der Aroio ist jetzt als App installiert.'), 'ok'); }
  }

  // copying works without HTTPS too (the Clipboard API needs a secure page)
  async function copy(text) {
    try {
      if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
      else {
        const ta = Object.assign(document.createElement('textarea'), { value: text });
        ta.setAttribute('readonly', '');
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.append(ta);
        ta.select();
        const ok = document.execCommand('copy');
        ta.remove();
        if (!ok) throw new Error('copy');
      }
      toast(t('Adresse kopiert.'), 'ok');
    } catch { toast(t('Kopieren ging nicht. Markiere die Adresse und kopiere sie selbst.'), 'danger'); }
  }
</script>

<div class="page">
  <PageHeader title={t('Als App nutzen')} backTo="/einstellungen" />

  {#if installed}
    <p class="notice ok"><SquareCheck size={20} aria-hidden="true" /><span>{t('Der Aroio läuft hier schon als App.')}</span></p>
  {:else}
    <section class="stack">
      <p>{t('Als App startet der Aroio ohne Browserleiste, in einem eigenen Fenster oder im Vollbild, und ist mit einem Klick oder Tipp da.')}</p>
      {#if app.installPrompt}
        <button class="btn primary big" type="button" onclick={install}><Download size={20} aria-hidden="true" />{t('Jetzt installieren')}</button>
      {:else}
        <h2 class="section-title">{t('Auf diesem Gerät')}</h2>
        <InstallGuide compact />
      {/if}
    </section>
  {/if}

  {#if !mobile}
    <section class="stack phone" aria-labelledby="phone-t">
      <h2 class="section-title with-icon" id="phone-t"><Smartphone size={22} aria-hidden="true" />{t('Aufs Handy holen')}</h2>
      <p>{t('Scanne den Code mit der Kamera des Handys. Der Aroio öffnet sich dort, dann wie oben „Zum Home-Bildschirm“.')}</p>
      {#if addresses.length > 1}
        <Segmented legend={t('Adresse im Code')} value={String(qrWhich)} onchange={(v) => { qrWhich = +v; qrFailed = false; }}
                   options={addresses.map((a, i) => ({ value: String(i), label: i === 0 ? `${n?.hostname || 'aroio'}.local` : t('IP-Adresse') }))} />
      {/if}
      {#if qrUrl && !qrFailed}
        <img class="qr" src={`/api/v1/qr.svg?text=${encodeURIComponent(qrUrl)}`} width="220" height="220"
             alt={t('QR-Code für {url}', { url: qrUrl })} onerror={() => (qrFailed = true)} />
      {/if}
      <p class="muted small">{t('Android findet „.local“-Namen oft nicht: dann den Code mit der IP-Adresse nehmen.')}</p>
    </section>
  {/if}

  <section class="stack" aria-labelledby="addr-t">
    <h2 class="section-title" id="addr-t">{t('Adressen')}</h2>
    <ul class="list">
      {#each addresses as a}
        <li class="addr"><span class="grow"><span class="muted small">{a.label}</span><br /><span class="mono">{a.url}</span></span>
          <button class="icon-btn" type="button" onclick={() => copy(a.url)} aria-label={t('{url} kopieren', { url: a.url })}><Copy size={20} aria-hidden="true" /></button></li>
      {/each}
    </ul>
  </section>
</div>

<style>
  section + section { margin-top: 28px; }
  .big { align-self: flex-start; }
  .with-icon { display: flex; gap: 10px; align-items: center; }
  .qr { background: #fff; border-radius: 16px; padding: 10px; align-self: flex-start; }
  .addr { display: flex; align-items: center; gap: 8px; padding: 10px 14px; min-height: 56px; }
  .mono { word-break: break-all; }
</style>
