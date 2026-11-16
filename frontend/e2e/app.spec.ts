import { expect, test, type Page } from "@playwright/test";

// Selection fields carry a stable data-field hook (their visible labels include step numbers).
const field = (page: Page, name: string) => page.locator(`label[data-field="${name}"] select`);

async function choose(page: Page, name: string, pattern: RegExp) {
  const select = field(page, name);
  await expect
    .poll(async () => (await select.locator("option").allTextContents()).some((t) => pattern.test(t)), { timeout: 120_000 })
    .toBe(true);
  const value = await select.evaluate(
    (s: HTMLSelectElement, src: string) => [...s.options].find((o) => new RegExp(src).test(o.text))!.value,
    pattern.source,
  );
  await select.selectOption(value);
}

async function openSession(page: Page, year: string, gp: RegExp, session: RegExp, a: RegExp, b: RegExp) {
  await page.goto("/");
  await choose(page, "Season", new RegExp(`^${year}`));
  await choose(page, "Grand Prix", gp);
  await choose(page, "Session", session);
  await choose(page, "Driver A", a);
  await choose(page, "Driver B", b);
}

function collectErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  page.on("console", (m) => m.type() === "error" && errors.push(`console: ${m.text()}`));
  page.on("response", (r) => r.status() >= 400 && errors.push(`${r.status()} ${r.url()}`));
  return errors;
}

test("defaults to full-data seasons and can show limited ones", async ({ page }) => {
  await page.goto("/");
  const seasons = field(page, "Season");
  await expect.poll(async () => (await seasons.locator("option").allTextContents()).length).toBeGreaterThan(0);
  const before = await seasons.locator("option").allTextContents();
  expect(before.some((t) => t.includes("limited"))).toBe(false);
  expect(before.some((t) => t.startsWith("2023"))).toBe(true);
  await page.getByLabel("show limited-data seasons").check();
  await expect.poll(async () => (await seasons.locator("option").allTextContents()).some((t) => t.startsWith("2019"))).toBe(true);
});

test("race: every tab renders without errors", async ({ page }) => {
  const errors = collectErrors(page);
  await openSession(page, "2024", /Italian/, /^Race/, /^LEC/, /^PIA/);

  await expect(page.locator(".uplot").first()).toBeVisible();
  await expect(page.getByText("Corner-by-corner")).toBeVisible();
  await expect(page.locator("table").first()).toBeVisible();

  const tabs: [string, string][] = [
    ["Lap overlay", "Brake point, minimum speed"],
    ["Tyre degradation", "Session-wide model (Model B)"],
    ["Driving style", "Line length through each corner"],
    ["Pace vs preservation", "Behaviour pattern by corner zone"],
    ["Strategy", "Cross-compound pace at equal"],
  ];
  for (const [tab, marker] of tabs) {
    await page.getByRole("button", { name: tab, exact: true }).click();
    await expect(page.getByText(marker).first()).toBeVisible();
  }
  expect(errors).toEqual([]);
});

test("qualifying disables tyre-age and strategy tabs", async ({ page }) => {
  await openSession(page, "2024", /Italian/, /^Qualifying/, /^LEC/, /^PIA/);
  for (const tab of ["Tyre degradation", "Pace vs preservation", "Strategy"]) {
    await expect(page.getByRole("button", { name: tab, exact: true })).toBeDisabled();
  }
  for (const tab of ["Lap comparison", "Lap overlay", "Driving style"]) {
    await expect(page.getByRole("button", { name: tab, exact: true })).toBeEnabled();
  }
});

test("practice: long runs are analysed and strategy is disabled", async ({ page }) => {
  const errors = collectErrors(page);
  await openSession(page, "2024", /Italian/, /^Practice 2/, /^LEC/, /^PIA/);
  await expect(page.getByRole("button", { name: "Strategy", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: "Tyre degradation", exact: true }).click();
  await expect(page.getByText("Long runs, whole field")).toBeVisible();
  await expect(page.getByText("Long-run laps only")).toBeVisible();
  expect(errors).toEqual([]);
});

test("welcome screen loads the example session", async ({ page }) => {
  const errors = collectErrors(page);
  await page.goto("/");
  await page.getByRole("button", { name: /Load example/ }).click();
  await expect(page.getByRole("heading", { name: "Italian Grand Prix" })).toBeVisible();
  await expect(page.locator(".uplot").first()).toBeVisible();
  expect(errors).toEqual([]);
});

test("season comparison starts and reports progress or results", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("tab", { name: "Season comparison" }).click();
  await field(page, "Season").selectOption("2024");
  await expect.poll(async () => (await field(page, "Driver A").locator("option").count()), { timeout: 300_000 }).toBeGreaterThan(2);
  await field(page, "Driver A").selectOption("LEC");
  await field(page, "Driver B").selectOption("SAI");
  await page.getByRole("button", { name: "Compare season" }).click();
  await expect(page.getByText(/Analysing races|Season scorecard/).first()).toBeVisible();
});

test("strategy simulator: Piastri on Norris's one-stop (Hungary 2025)", async ({ page }) => {
  const errors = collectErrors(page);
  await openSession(page, "2025", /Hungar/, /^Race/, /^NOR/, /^PIA/);
  await page.getByRole("button", { name: "Strategy", exact: true }).click();
  await expect(page.getByText("What-if strategy simulator")).toBeVisible();
  await expect(page.getByText(/Model accuracy here/)).toBeVisible();
  await page.getByRole("button", { name: "NOR's strategy" }).click();
  await page.getByRole("button", { name: "Simulate", exact: true }).click();
  await expect(page.getByText("Race time vs their real strategy").first()).toBeVisible();
  await expect(page.getByText(/90% range/).first()).toBeVisible();
  await expect(page.getByText(/Chance NOR finishes ahead of PIA/)).toBeVisible();
  await page.getByRole("button", { name: "Find best strategies" }).click();
  await expect(page.getByRole("button", { name: "Load into builder" }).first()).toBeVisible();
  expect(errors).toEqual([]);
});
