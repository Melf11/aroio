<script>
  import { Smartphone, Trash2, BluetoothSearching } from '@lucide/svelte';
  import PageHeader from '../../components/PageHeader.svelte';
  import Toggle from '../../components/Toggle.svelte';
  import { app, toast } from '../../lib/state.svelte.js';
  import { api, config } from '../../lib/api.js';
  import { t } from '../../lib/i18n.svelte.js';
  const b = $derived(app.topics.bluetooth);
  const left = $derived(b?.pairing_until ? Math.max(0, Math.round(b.pairing_until - app.now)) : 0);
  const save = async (patch) => { try { await config(patch); } catch (e) { toast(e.message, 'danger'); } };
  const pairing = (s) => api.post('/bluetooth/pairing', { seconds: s }).catch((e) => toast(e.message, 'danger'));
  const remove = (d) => api.del('/bluetooth/devices/' + encodeURIComponent(d.address)).then(() => toast(t('„{n}“ entfernt.', { n: d.name }))).catch((e) => toast(e.message, 'danger'));
</script>

<div class="page">
  <PageHeader title="Bluetooth" backTo="/einstellungen" />
  {#if b}
    <ul class="list"><li><Toggle label="Bluetooth" description={t('Der Aroio erscheint als „{n}“.', { n: b.name })} checked={b.enabled} onchange={(v) => save({ sources: { bluetooth: { enabled: v } } })} /></li></ul>
    {#if b.enabled}
      <div class="card stack pair">
        {#if b.pairing && left > 0}
          <p role="status"><BluetoothSearching size={22} aria-hidden="true" class="inline" /> {t('Kopplung offen, noch {s} Sekunden. Wähle jetzt auf deinem Handy „{n}“ in den Bluetooth-Einstellungen.', { s: left, n: b.name })}</p>
          <button class="btn" type="button" onclick={() => pairing(0)}>{t('Kopplung beenden')}</button>
        {:else}
          <p>{t('Um ein neues Handy zu verbinden, öffne die Kopplung für 2 Minuten.')}</p>
          <button class="btn primary" type="button" onclick={() => pairing(120)}>{t('Neues Gerät koppeln')}</button>
        {/if}
      </div>
      <h2 class="section-title">{t('Gekoppelte Geräte')}</h2>
      {#if b.devices.length}
        <ul class="list">
          {#each b.devices as d}
            <li class="dev"><Smartphone size={20} aria-hidden="true" /><span class="grow">{d.name}{#if d.connected} <span class="badge ok">{t('Verbunden')}</span>{/if}</span>
              <button class="icon-btn" type="button" onclick={() => remove(d)} aria-label={t('{n} entfernen', { n: d.name })}><Trash2 size={18} aria-hidden="true" /></button></li>
          {/each}
        </ul>
      {:else}<p class="muted">{t('Noch keine Geräte gekoppelt.')}</p>{/if}
      <ul class="list ar"><li><Toggle label={t('Automatisch wieder verbinden')} description={t('Bekannte Geräte verbinden sich nach dem Einschalten von selbst.')} checked={b.auto_reconnect} onchange={(v) => save({ sources: { bluetooth: { auto_reconnect: v } } })} /></li></ul>
    {/if}
  {/if}
</div>

<style>
  .pair { margin-top: 16px; align-items: flex-start; }
  :global(.inline) { display: inline; vertical-align: -5px; color: var(--brand-ink); }
  .dev { display: flex; align-items: center; gap: 12px; padding: 8px 8px 8px 16px; min-height: 56px; }
  .ar { margin-top: 16px; }
</style>
