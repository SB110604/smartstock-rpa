import { expect, type Page } from '@playwright/test';

export const USERS = {
  admin: ['admin@demo.in', 'Admin@123'],
  manager: ['manager@demo.in', 'Manager@123'],
  staff: ['staff@demo.in', 'Staff@123'],
  supplier: ['supplier1@demo.in', 'Supplier@123'],
} as const;

export async function login(page: Page, role: keyof typeof USERS): Promise<void> {
  const [email, password] = USERS[role];
  await page.goto('/login');
  await page.evaluate(() => localStorage.clear());
  await page.goto('/login');
  await page.getByLabel('Email').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

export async function logout(page: Page): Promise<void> {
  await page.evaluate(() => localStorage.removeItem('ss.tokens'));
}
