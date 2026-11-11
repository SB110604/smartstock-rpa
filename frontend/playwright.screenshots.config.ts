import { defineConfig, devices } from '@playwright/test';
import base from './playwright.config';

/** `npm run screenshots`: captures docs/screenshots/*.png for the README from a running, seeded stack. */
export default defineConfig({
  ...base,
  testDir: './tests/screenshots',
  reporter: 'list',
  projects: [{ name: 'screenshots', use: { ...devices['Desktop Chrome'] } }],
});
