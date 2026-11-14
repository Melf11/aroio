<script>
  import PageHeader from '../components/PageHeader.svelte';
  import QueueList from '../components/QueueList.svelte';
  import { t } from '../lib/i18n.svelte.js';
</script>

<div class="page">
  <PageHeader title={t('Warteschlange')} backTo="/" />
  <QueueList />
</div>
