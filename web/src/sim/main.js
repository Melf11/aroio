import { mount } from 'svelte';
import '../app.css';
import Sim from './Sim.svelte';
import { connect } from '../lib/state.svelte.js';

connect();
mount(Sim, { target: document.getElementById('sim') });
