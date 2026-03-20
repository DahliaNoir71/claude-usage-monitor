/**
 * Claude Usage Monitor - Module Loader & App Controller
 */

const APP = {
  currentTab: 'overview',
  loadedModules: {},
  data: {},
  charts: {},

  async init() {
    console.log('Initializing Claude Usage Monitor...');

    // Load initial tab
    await this.switchTab('overview');

    // Set up auto-refresh
    this.startAutoRefresh();
  },

  async switchTab(tabName) {
    // Unload previous charts if switching tabs
    this.destroyCharts();

    // Update sidebar
    document.querySelectorAll('.sidebar-link').forEach(link => {
      link.classList.remove('active');
    });
    document.querySelector(`[data-tab="${tabName}"]`).classList.add('active');

    // Load module if not already loaded
    if (!this.loadedModules[tabName]) {
      await this.loadModule(tabName);
    }

    // Show the module
    const mainContent = document.getElementById('mainContent');
    mainContent.innerHTML = this.loadedModules[tabName];

    // Execute module initialization script if it exists
    const script = mainContent.querySelector('script');
    if (script) {
      // Create a new function from the script content and execute it
      // This allows each module to have its own initialization
      const initFunc = new Function(script.textContent);
      try {
        initFunc.call(window);
      } catch (e) {
        console.error(`Error initializing ${tabName}:`, e);
      }
    }

    this.currentTab = tabName;
  },

  async loadModule(tabName) {
    try {
      const response = await fetch(`modules/${tabName}.html`);
      if (!response.ok) throw new Error(`Failed to load ${tabName}`);
      this.loadedModules[tabName] = await response.text();
    } catch (error) {
      console.error(`Error loading module ${tabName}:`, error);
      this.loadedModules[tabName] = `<div class="loading"><p>Erreur lors du chargement du module ${tabName}</p></div>`;
    }
  },

  destroyCharts() {
    // Destroy all Chart.js instances to prevent memory leaks
    if (typeof APP_STATE !== 'undefined') {
      Object.values(APP_STATE.charts).forEach(chart => {
        if (chart && typeof chart.destroy === 'function') {
          chart.destroy();
        }
      });
      APP_STATE.charts = {};
    }
  },

  startAutoRefresh() {
    // Refresh data every 30 seconds
    setInterval(() => {
      this.refreshData();
    }, 30000);
  },

  async refreshData() {
    try {
      // Fetch fresh data from API
      const response = await fetch('/api/analysis');
      if (response.ok) {
        this.data = await response.json();

        // If currently on overview, refresh displayed data
        if (this.currentTab === 'overview' && window.refreshOverview) {
          window.refreshOverview(this.data);
        }
      }
    } catch (error) {
      console.error('Error refreshing data:', error);
    }
  },
};

// Make switchTab available globally for onclick handlers
function switchTab(tabName) {
  APP.switchTab(tabName);
}

// Initialize app when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => APP.init());
} else {
  APP.init();
}
