import { expect, test } from '@playwright/test';
import { login } from './helpers';

/** The chat panel opens without crashing the page and answers without an LLM (rule-based fallback). */
test('assistant answers in the chat panel', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await login(page, 'manager');
  await page.getByRole('button', { name: 'Ask assistant' }).click();
  const chat = page.getByRole('dialog');
  const box = chat.getByRole('textbox');
  await box.fill('Which items expire this week?');
  await box.press('Enter');
  await expect(chat.getByText(/expire within 7 days/).last()).toBeVisible({ timeout: 30_000 });
  expect(errors).toEqual([]);
});
