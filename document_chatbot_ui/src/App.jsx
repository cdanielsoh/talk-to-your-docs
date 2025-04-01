import React from 'react';
import Layout from './components/Layout/Layout';
import './components/Layout/Layout.css';

async function loadConfig() {
  const response = await fetch('/config.json');
  return await response.json();
}

function App() {
  return (
    <Layout />
  );
}

export default App;
