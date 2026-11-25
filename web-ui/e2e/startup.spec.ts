import { expect, test, type Response } from '@playwright/test';

import { deleteWithLaunchToken, postWithLaunchToken } from './session';

const api = '/api/v3';
const projectsUrl = `http://127.0.0.1:8765${api}/projects`;

test('loads a saved project on Studio startup', async ({ page, request }) => {
  const project = {
    format_version: 3,
    id: 'a000_startup_e2e',
    name: 'Saved startup project',
    runtime: { mode: 'batch', options: {} },
    graph: {
      name: 'startup-e2e',
      nodes: [{
        id: 'calculate',
        operator: { kind: 'expression', expression: 'result = value + 1' },
      }],
    },
    data_sources: [{
      id: 'sample',
      input: 'input',
      format: 'inline_json',
      data: [{ value: 1 }],
    }],
  };
  const created = await postWithLaunchToken(request, projectsUrl, { data: project });
  expect(created.status(), await created.text()).toBe(201);

  try {
    const responses = new Map<string, Response>();
    page.on('response', (response) => {
      if (response.request().method() === 'GET') {
        responses.set(new URL(response.url()).pathname, response);
      }
    });
    await page.goto('/');

    for (const path of ['/catalog', '/capabilities', '/projects', `/projects/${project.id}`]) {
      await expect.poll(() => responses.has(api + path), { message: path }).toBe(true);
      expect(responses.get(api + path)?.status(), path).toBe(200);
    }
    const capabilities = await responses.get(`${api}/capabilities`)?.json();
    expect(capabilities.schemaVersion).toBe(3);
    expect(capabilities.runtime.packageVersion).toEqual(
      process.env.CALC_FLOW_TEST_VERSION ?? expect.any(String),
    );
    await expect(page.getByLabel('Project', { exact: true })).toHaveValue(project.id);
    await expect(page.getByLabel('Project name')).toHaveValue(project.name);
    await expect(page.locator('.toast')).toHaveCount(0);
  } finally {
    await deleteWithLaunchToken(request, `${projectsUrl}/${project.id}`);
  }
});
