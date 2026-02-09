// cypress.config.cjs
const { defineConfig } = require("cypress");

module.exports = defineConfig({
  projectId: "wm57gz", // from Cypress Cloud
  e2e: {
    baseUrl: "http://localhost:3000",
    supportFile: false, // disable support file if not needed
  },
});