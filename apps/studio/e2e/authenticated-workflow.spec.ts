import { expect, test } from '@playwright/test';
import type { BrowserContext, Page } from '@playwright/test';
import { readFile } from 'node:fs/promises';

const E2E_EMAIL = 'browser-e2e@example.com';
const E2E_PASSWORD = 'browser-e2e-password';
const RESULT_PROJECT = 'Browser E2E Results';
const RESULT_JOB = 'Browser E2E completed job';
const UNCERTAIN_JOB = 'Browser E2E uncertain provider job';
const RETRY_SAFE_JOB = 'Browser E2E retry-safe provider job';
const RECONCILIATION_JOB = 'Browser E2E reconciliation required job';
const QUEUED_CANCELLATION_JOB = 'Browser E2E queued cancellation job';
const PROCESSING_CANCELLATION_JOB = 'Browser E2E processing cancellation job';
const RECONCILIATION_TOKEN = 'or_browser_e2e_pending';
const RESULT_URL =
  'https://docs.google.com/document/d/browser-e2e-document/edit';
let sharedSessionCookies:
  | Awaited<ReturnType<BrowserContext['cookies']>>
  | null = null;

test.describe.configure({ mode: 'serial' });

async function login(page: Page) {
  await page.goto('/');

  if (sharedSessionCookies) {
    await page.context().addCookies(sharedSessionCookies);
    await page.reload();
  } else {
    await expect(page.getByRole('heading', { name: 'Вход' })).toBeVisible();
    await page.getByLabel('Email').fill(E2E_EMAIL);
    await page.getByLabel('Пароль').fill(E2E_PASSWORD);
    await page.getByRole('button', { name: 'Войти' }).click();
  }

  const navigation = page.getByRole('navigation', {
    name: 'Основная навигация',
  });
  await expect(navigation).toBeVisible();
  sharedSessionCookies ??= await page.context().cookies();
  return navigation;
}

async function openResultTranscriptions(
  page: Page,
  navigation: ReturnType<Page['getByRole']>,
) {
  await navigation
    .getByRole('button', { name: 'Транскрибации', exact: true })
    .click();
  await expect(page).toHaveURL(/\/transcriptions$/);
  await expect(
    page.getByRole('region', { name: `Подготовка ${RESULT_PROJECT}` }),
  ).toBeVisible();
}

function trackExternalOrJobMutations(page: Page) {
  const requests: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    const isExternalIntegration =
      url.hostname.includes('google') ||
      url.hostname.includes('elevenlabs') ||
      url.hostname.includes('cloudflarestorage');
    const isJobMutation =
      request.method() !== 'GET' && url.pathname.startsWith('/api/jobs/');
    if (isExternalIntegration || isJobMutation) {
      requests.push(`${request.method()} ${url.origin}${url.pathname}`);
    }
  });
  return requests;
}

function isJobProgressUrl(value: string) {
  return new URL(value).pathname.endsWith('/jobs/progress');
}

function browserLocalWavFixture() {
  const sampleRate = 8_000;
  const frames = sampleRate / 4;
  const buffer = Buffer.alloc(44 + frames * 2);
  buffer.write('RIFF', 0);
  buffer.writeUInt32LE(buffer.length - 8, 4);
  buffer.write('WAVE', 8);
  buffer.write('fmt ', 12);
  buffer.writeUInt32LE(16, 16);
  buffer.writeUInt16LE(1, 20);
  buffer.writeUInt16LE(1, 22);
  buffer.writeUInt32LE(sampleRate, 24);
  buffer.writeUInt32LE(sampleRate * 2, 28);
  buffer.writeUInt16LE(2, 32);
  buffer.writeUInt16LE(16, 34);
  buffer.write('data', 36);
  buffer.writeUInt32LE(frames * 2, 40);
  for (let frame = 0; frame < frames; frame += 1) {
    const sample = Math.round(Math.sin((frame / sampleRate) * Math.PI * 2 * 440) * 8_000);
    buffer.writeInt16LE(sample, 44 + frame * 2);
  }
  return buffer;
}

test('authenticated user opens transcriptions and reads a completed job result', async ({
  page,
}) => {
  const navigation = await login(page);
  await openResultTranscriptions(page, navigation);

  await page
    .locator('details.recent-jobs')
    .getByText(/^Недавние транскрибации · \d+$/)
    .click();
  const jobCard = page
    .locator('article.source-card')
    .filter({ hasText: RESULT_JOB })
    .first();
  await expect(jobCard.getByText('Статус: Завершена')).toBeVisible();
  const resultJobId = await jobCard.getAttribute('data-job-id');
  expect(resultJobId).toMatch(/^[0-9a-f-]{36}$/);
  const reconciliationResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      response.url().endsWith(`/api/jobs/${resultJobId}/output-reconciliation`),
  );
  // Primary document access is available before fetching technical details.
  await expect(jobCard.getByRole('link', { name: 'Открыть документ', exact: true })).toHaveAttribute('href', RESULT_URL);
  await jobCard.getByRole('button', { name: 'Показать результаты и детали', exact: true }).click();
  const reconciliationResponse = await reconciliationResponsePromise;
  expect(reconciliationResponse.status()).toBe(200);
  const reconciliation = await reconciliationResponse.json();
  expect(reconciliation).toMatchObject({
    job_status: 'completed',
    available: false,
    counts: {
      reconciliation_required: 0,
      resolved: 1,
      conflict: 0,
    },
  });
  expect(reconciliation).toMatchObject({ job_id: resultJobId });

  const resultDrawer = page.getByRole('dialog');
  await expect(resultDrawer).toBeVisible();
  await expect(resultDrawer.getByRole('heading', { name: 'Результаты' })).toBeVisible();
  await expect(resultDrawer.getByRole('link', { name: 'Открыть документ' })).toHaveAttribute(
    'href',
    RESULT_URL,
  );
  const jobDetail = resultDrawer.getByRole('region', {
    name: 'Подробности транскрибации',
  });
  await expect(jobDetail.getByRole('heading', { name: 'Файлы задачи' })).toBeVisible();
  await expect(jobDetail.getByText('Статус обработки: Завершена')).toBeVisible();
  await expect(jobDetail).not.toContainText('Статус файла: queued');
  await expect(jobDetail).not.toContainText('Статус обработки: В очереди');
  await expect(
    jobCard.getByRole('region', { name: 'Проверка результата в Google Drive' }),
  ).toHaveCount(0);
  await expect(
    jobCard.getByRole('button', {
      name: 'Проверить созданный документ в Google Drive',
    }),
  ).toHaveCount(0);

  await resultDrawer.getByRole('button', { name: 'Закрыть детали' }).click();
  await expect(jobCard.getByRole('button', { name: 'Показать результаты и детали' })).toBeFocused();
  await navigation
    .getByRole('button', { name: 'Настройки', exact: true })
    .click();
  await page.getByRole('tab', { name: 'Для поддержки' }).click();
  await page.getByText('Расширенные технические фильтры', { exact: true }).click();
  await page
    .getByRole('textbox', { name: 'Internal task ID', exact: true })
    .fill(resultJobId);
  const diagnosticsResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      response.url().includes('/diagnostics/events?') &&
      response.url().includes(`job_id=${resultJobId}`),
  );
  await page
    .getByRole('button', { name: 'Обновить события', exact: true })
    .click();
  const diagnosticsResponse = await diagnosticsResponsePromise;
  expect(diagnosticsResponse.status()).toBe(200);
  const diagnostics = await diagnosticsResponse.json();
  expect(
    (diagnostics as { events?: Array<{ event_code?: string }> }).events?.map(
      (event) => event.event_code,
    ),
  ).toEqual(['JOB_COMPLETED', 'OUTPUT_PERSISTED', 'JOB_CREATED']);
  const diagnosticsJson = JSON.stringify(diagnostics);
  expect(diagnosticsJson).not.toContain('browser-e2e-audio.mp3');
  expect(diagnosticsJson).not.toContain('browser-e2e-document');
  expect(diagnosticsJson).not.toContain('browser-e2e-source');

  const diagnosticEvents = page.getByRole('region', {
    name: 'События диагностики',
  });
  await expect(
    diagnosticEvents.getByText(/Журнал событий · требует внимания 0 · информационных 3/),
  ).toBeVisible();
  await expect(
    diagnosticEvents.getByText('JOB_COMPLETED', { exact: true }),
  ).toBeHidden();
  await diagnosticEvents.getByText(/Журнал событий ·/).click();
  await diagnosticEvents.getByText('Информационные события (3)', { exact: true }).click();
  await expect(
    diagnosticEvents.getByText('Транскрибация завершена', { exact: true }),
  ).toBeVisible();
  await expect(
    diagnosticEvents.getByText('Задача транскрибации создана', { exact: true }),
  ).toBeVisible();
  const eventDetails = diagnosticEvents.locator('li.diagnostics-event details');
  await expect(eventDetails).toHaveCount(3);
  for (let index = 0; index < 3; index += 1) {
    await eventDetails.nth(index).locator('summary').click();
  }
  await expect(diagnosticEvents.getByText('JOB_COMPLETED', { exact: true })).toBeVisible();
  await expect(diagnosticEvents.getByText('OUTPUT_PERSISTED', { exact: true })).toBeVisible();
  await expect(diagnosticEvents.getByText('JOB_CREATED', { exact: true })).toBeVisible();
  await expect(diagnosticEvents).toContainText('final_job_status');
  await expect(diagnosticEvents).toContainText('completed');
  await expect(diagnosticEvents).toContainText('output_count');
  await expect(diagnosticEvents).toContainText('1');

  await page.getByRole('tab', { name: 'Аккаунт' }).click();
  await page.getByRole('button', { name: 'Выйти' }).click();
  sharedSessionCookies = null;
  await expect(page.getByRole('heading', { name: 'Вход' })).toBeVisible();
});

test('mobile Drive dialog stays inside the viewport and locks page scrolling', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route('**/api/google/connection', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        connected: true,
        status: 'active',
        google_email: 'browser-e2e@example.com',
        scopes:
          'openid email https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/drive.readonly',
        connected_at: '2026-08-30T00:00:00Z',
        revoked_at: null,
        picker_ready: true,
        picker_configured: true,
        picker_scope_ready: true,
        reconnect_required: false,
      }),
    });
  });
  await page.route('**/api/google/picker/session', async (route) => {
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        access_token: 'browser-e2e-picker-token',
        api_key: 'browser-e2e-public-key',
        app_id: '123456789',
        scope_ready: true,
      }),
    });
  });
  await page.route('https://www.googleapis.com/drive/v3/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/files/root')) {
      await route.fulfill({
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'root-id',
          name: 'Мой диск',
          mimeType: 'application/vnd.google-apps.folder',
        }),
      });
      return;
    }
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify(
        url.pathname.endsWith('/drives') ? { drives: [] } : { files: [] },
      ),
    });
  });

  const navigation = await login(page);
  await openResultTranscriptions(page, navigation);
  await page
    .getByRole('button', { name: 'Выбрать папку результата для задачи 1' })
    .click();

  const dialog = page.getByRole('dialog', {
    name: 'Выберите папку для результатов',
  });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByLabel('Сортировка папок и файлов')).toBeEnabled();
  const geometry = await dialog.evaluate((element) => {
    const box = element.getBoundingClientRect();
    return {
      left: box.left,
      right: box.right,
      width: box.width,
      scrollWidth: element.scrollWidth,
      clientWidth: element.clientWidth,
      bodyOverflow: document.body.style.overflow,
      rootOverflow: document.documentElement.style.overflow,
    };
  });
  expect(geometry.left).toBeGreaterThanOrEqual(0);
  expect(geometry.right).toBeLessThanOrEqual(390);
  expect(geometry.width).toBeLessThanOrEqual(390);
  expect(geometry.scrollWidth).toBeLessThanOrEqual(geometry.clientWidth);
  expect(geometry.bodyOverflow).toBe('hidden');
  expect(geometry.rootOverflow).toBe('hidden');

  // Check the visible controls, not only the outer clipped container.
  for (const viewport of [{ width: 1280, height: 720 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    const controls = await dialog.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const footer = element.querySelector('.google-drive-folder-picker-actions')!.getBoundingClientRect();
      const breadcrumb = element.querySelector('.google-drive-folder-breadcrumbs')!.getBoundingClientRect();
      const content = element.querySelector('.google-drive-folder-picker-content')!.getBoundingClientRect();
      return { bottom: box.bottom, footerBottom: footer.bottom, breadcrumbHeight: breadcrumb.height, contentHeight: content.height };
    });
    expect(controls.bottom).toBeLessThanOrEqual(viewport.height);
    expect(controls.footerBottom).toBeLessThanOrEqual(controls.bottom);
    expect(controls.breadcrumbHeight).toBeLessThan(80);
    expect(controls.contentHeight).toBeGreaterThan(0);
  }

  const pageScrollBefore = await page.evaluate(() => window.scrollY);
  await page.mouse.move(380, 820);
  await page.mouse.wheel(0, 800);
  await expect.poll(() => page.evaluate(() => window.scrollY)).toBe(pageScrollBefore);
  await dialog.getByRole('button', { name: 'Закрыть выбор папки' }).click();
  await expect(dialog).toHaveCount(0);
  expect(await page.evaluate(() => document.body.style.overflow)).toBe('');
});

test('account settings revoke selected and all other active sessions', async ({
  browser,
  page,
}) => {
  const navigation = await login(page);
  const secondaryContexts = await Promise.all([
    browser.newContext({ baseURL: 'http://127.0.0.1:4173' }),
    browser.newContext({ baseURL: 'http://127.0.0.1:4173' }),
  ]);
  try {
    const secondaryPages = await Promise.all(
      secondaryContexts.map(async (context) => {
        const secondary = await context.newPage();
        await secondary.goto('/');
        await expect(secondary.getByRole('heading', { name: 'Вход' })).toBeVisible();
        await secondary.getByLabel('Email').fill(E2E_EMAIL);
        await secondary.getByLabel('Пароль').fill(E2E_PASSWORD);
        await secondary.getByRole('button', { name: 'Войти' }).click();
        await expect(
          secondary.getByRole('navigation', { name: 'Основная навигация' }),
        ).toBeVisible();
        return secondary;
      }),
    );

    await navigation
      .getByRole('button', { name: 'Настройки', exact: true })
      .click();
    const sessions = page.getByRole('region', { name: 'Активные сессии' });
    await expect(sessions.getByText('Текущая сессия', { exact: true })).toBeVisible();
    await expect(sessions.getByText('Другая сессия', { exact: true })).toHaveCount(2);

    page.once('dialog', (dialog) => dialog.accept());
    const targetedResponse = page.waitForResponse(
      (response) =>
        response.request().method() === 'DELETE' &&
        /\/api\/auth\/sessions\/[0-9a-f-]{36}$/.test(response.url()),
    );
    await sessions
      .getByRole('button', { name: 'Завершить сессию', exact: true })
      .first()
      .click();
    expect((await targetedResponse).status()).toBe(200);
    await expect(sessions.getByText('Сессия завершена.', { exact: true })).toBeVisible();
    await expect(sessions.getByText('Другая сессия', { exact: true })).toHaveCount(1);

    page.once('dialog', (dialog) => dialog.accept());
    const revokeOthersResponse = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        response.url().endsWith('/api/auth/sessions/revoke-other'),
    );
    await sessions
      .getByRole('button', { name: 'Завершить все остальные', exact: true })
      .click();
    expect((await revokeOthersResponse).status()).toBe(200);
    await expect(
      sessions.getByText('Все остальные сессии завершены.', { exact: true }),
    ).toBeVisible();
    await expect(sessions.getByText('Других активных сессий нет.')).toBeVisible();
    await expect(
      page.getByRole('navigation', { name: 'Основная навигация' }),
    ).toBeVisible();

    for (const secondary of secondaryPages) {
      await secondary.reload();
      await expect(secondary.getByRole('heading', { name: 'Вход' })).toBeVisible();
    }
  } finally {
    await Promise.all(secondaryContexts.map((context) => context.close()));
  }
});

test('Audio workspace processes a device WAV in-browser without uploading source bytes', async ({
  page,
}) => {
  const navigation = await login(page);
  const uploadMutations: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/local-upload/')) {
      uploadMutations.push(`${request.method()} ${request.url()}`);
    }
  });

  await navigation
    .getByRole('button', { name: 'Подготовка аудио', exact: true })
    .click();
  await expect(page).toHaveURL(/\/audio$/);
  await page
    .getByRole('tab', { name: 'Обработать на устройстве', exact: true })
    .click();
  await page
    .getByLabel('Выбрать файлы для обработки на устройстве')
    .setInputFiles({
      name: 'Лекция 1. Предмет, задачи и методы социальной психологии.wav',
      mimeType: 'audio/wav',
      buffer: browserLocalWavFixture(),
    });

  await expect(
    page.getByText('Выбрано файлов: 1 · обработка на устройстве'),
  ).toBeVisible();
  await expect(page.getByLabel('Формат результата')).toHaveValue('wav');
  await expect(page.getByLabel('Формат результата')).toBeDisabled();
  const parameters = page
    .getByRole('heading', { name: '2. Параметры' })
    .locator('..');
  await parameters.getByRole('checkbox', { name: 'Уменьшить длинные паузы в аудио или видео' }).check();
  await parameters.getByText('Дополнительные настройки пауз').click();
  const threshold = parameters.getByLabel('Что считать тишиной, dB');
  await threshold.fill('');
  await expect(threshold).toHaveValue('');
  await threshold.pressSequentially('-');
  await expect(threshold).toHaveValue('-');
  await parameters.getByRole('button', { name: 'Обработать на устройстве', exact: true }).click();
  await expect(page.getByText(/введите число от −60 до −10/)).toBeVisible();
  await expect(page.getByRole('heading', { name: '3. Локальные результаты' })).toHaveCount(0);
  await threshold.fill('');
  await threshold.pressSequentially('-45');
  await expect(threshold).toHaveValue('-45');
  const keep = parameters.getByLabel('Сколько паузы оставить, сек');
  await keep.fill('');
  await keep.pressSequentially('0.3');
  await expect(keep).toHaveValue('0,3');
  await parameters
    .getByRole('button', { name: 'Обработать на устройстве', exact: true })
    .click();

  const localResults = page.getByRole('heading', {
    name: '3. Локальные результаты',
  }).locator('..');
  await expect(localResults).toBeVisible();
  const download = localResults.getByRole('link', { name: 'Скачать файл' });
  await expect(download).toHaveAttribute('href', /^blob:/);
  await expect(download).toHaveAttribute('download', 'Лекция 1. Предмет, задачи и методы социальной психологии.wav');
  await expect(localResults.getByRole('region', { name: 'Анализ звука и пауз' })).toBeVisible();
  await expect(localResults.getByText(/^Исходно:.*результат:/)).toBeVisible();
  expect(uploadMutations).toEqual([]);
});

test('Live captures browser audio, exports text and restores its encrypted draft after reload', async ({
  page,
}) => {
  await page.addInitScript(() => {
    const audioTrack = {
      stop() {},
      addEventListener() {},
    };
    const stream = {
      getTracks: () => [audioTrack],
      getAudioTracks: () => [audioTrack],
    };
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        enumerateDevices: async () => [
          {
            deviceId: 'browser-e2e-mic',
            groupId: 'browser-e2e-group',
            kind: 'audioinput',
            label: 'Browser E2E microphone',
            toJSON: () => ({}),
          },
        ],
        getUserMedia: async () => stream,
        getDisplayMedia: async () => stream,
        addEventListener() {},
        removeEventListener() {},
      },
    });
    class FakeAudioContext {
      state = 'running';
      sampleRate = 48_000;
      currentTime = 12;
      destination = {};
      analyserIndex = 0;
      async resume() {}
      async close() {}
      createMediaStreamSource() {
        return { connect() {}, disconnect() {} };
      }
      createMediaStreamDestination() {
        return { stream, disconnect() {} };
      }
      createAnalyser() {
        const sample = this.analyserIndex === 0 ? 0.2 : 0.02;
        this.analyserIndex += 1;
        return {
          fftSize: 2_048,
          connect() {},
          disconnect() {},
          getFloatTimeDomainData(target: Float32Array) {
            target.fill(sample);
          },
        };
      }
      createScriptProcessor() {
        const processor = {
          onaudioprocess: null as ((event: AudioProcessingEvent) => void) | null,
          connect() {},
          disconnect() {},
        };
        window.setTimeout(() => {
          processor.onaudioprocess?.({
            inputBuffer: {
              getChannelData: () => new Float32Array(48),
            },
          } as AudioProcessingEvent);
        }, 0);
        return processor;
      }
      createGain() {
        const gain = {
          value: 1,
          setTargetAtTime(value: number) {
            this.value = value;
          },
        };
        return {
          gain,
          connect() {},
          disconnect() {},
        };
      }
    }
    class FakeWebSocket {
      static CONNECTING = 0;
      static OPEN = 1;
      static CLOSED = 3;
      readyState = FakeWebSocket.CONNECTING;
      onopen: ((event: Event) => void) | null = null;
      onmessage: ((event: MessageEvent) => void) | null = null;
      onerror: ((event: Event) => void) | null = null;
      onclose: ((event: CloseEvent) => void) | null = null;
      constructor() {
        window.setTimeout(() => {
          this.readyState = FakeWebSocket.OPEN;
          this.onopen?.(new Event('open'));
          this.onmessage?.(
            new MessageEvent('message', {
              data: JSON.stringify({ message_type: 'session_started' }),
            }),
          );
          this.onmessage?.(
            new MessageEvent('message', {
              data: JSON.stringify({
                message_type: 'partial_transcript',
                text: 'предварительный текст',
              }),
            }),
          );
          this.onmessage?.(
            new MessageEvent('message', {
              data: JSON.stringify({
                message_type: 'committed_transcript',
                text: 'подтверждённый текст',
              }),
            }),
          );
        }, 0);
      }
      send() {}
      close() {
        this.readyState = FakeWebSocket.CLOSED;
        this.onclose?.(new CloseEvent('close', { code: 1000 }));
      }
    }
    Object.defineProperty(window, 'AudioContext', {
      configurable: true,
      value: FakeAudioContext,
    });
    Object.defineProperty(window, 'WebSocket', {
      configurable: true,
      value: FakeWebSocket,
    });
  });
  await page.route('**/api/credentials', async (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        credentials: [
          {
            id: 'browser-e2e-realtime-credential',
            provider: 'elevenlabs',
            label: 'Browser E2E realtime',
            status: 'active',
            active_version: 1,
            masked_value: '••••e2e',
          },
        ],
      }),
    });
  });
  let capabilityRequests = 0;
  await page.route('**/api/projects/*/realtime/capability', async (route) => {
    capabilityRequests += 1;
    expect(route.request().method()).toBe('POST');
    expect(route.request().postDataJSON()).toMatchObject({
      provider_credential_id: 'browser-e2e-realtime-credential',
      language: 'ru',
    });
    await route.fulfill({
      contentType: 'application/json',
      body: JSON.stringify({
        websocket_url:
          'wss://api.elevenlabs.io/v1/speech-to-text/realtime?model_id=scribe_v2_realtime&token=sutkn_browser_e2e&audio_format=pcm_16000&commit_strategy=vad&language_code=ru',
        expires_in_seconds: 900,
        model_id: 'scribe_v2_realtime',
        audio_format: 'pcm_16000',
        commit_strategy: 'vad',
      }),
    });
  });

  const navigation = await login(page);
  await openResultTranscriptions(page, navigation);
  await page.getByRole('tab', { name: 'Live-транскрибация' }).click();
  const live = page.getByRole('region', { name: 'Live-транскрибация' });
  await expect(live).toBeVisible();
  await expect(live.getByLabel('Звук вкладки или экрана')).toBeChecked();
  await expect(live.getByLabel('Микрофон или аудиовход')).not.toBeChecked();
  await live.getByLabel('Микрофон или аудиовход').check();
  await expect(live.getByLabel('Устройство ввода')).toContainText(
    'Browser E2E microphone',
  );

  await live.getByRole('button', { name: 'Начать' }).click();
  await expect(live.getByText('Распознаём речь')).toBeVisible();
  await expect(live.getByText('Звук вкладки · 80%')).toBeVisible();
  await expect(live.getByText('Микрофон · 8%')).toBeVisible();
  await expect(
    live.getByText('подтверждённый текст', { exact: true }),
  ).toBeVisible();
  expect(capabilityRequests).toBe(1);
  await expect(live).not.toContainText('sutkn_browser_e2e');

  await navigation.getByRole('button', { name: 'Обзор', exact: true }).click();
  await expect(live).toBeHidden();
  await navigation
    .getByRole('button', { name: 'Транскрибации', exact: true })
    .click();
  await expect(live).toBeVisible();
  await expect(live.getByText('Остановлено')).toBeVisible();
  await expect(
    live.getByText('подтверждённый текст', { exact: true }),
  ).toBeVisible();

  await page.getByRole('tab', { name: 'Обычная транскрибация' }).click();
  await expect(live).toBeHidden();
  await page.getByRole('tab', { name: 'Live-транскрибация' }).click();
  await expect(
    live.getByText('подтверждённый текст', { exact: true }),
  ).toBeVisible();
  expect(capabilityRequests).toBe(1);

  await expect(live.getByText('Live-текст сохранён локально и в Studio до ручной очистки.')).toBeVisible();
  await live.getByLabel('Формат скачивания Live').selectOption('md');
  const downloadPromise = page.waitForEvent('download');
  await live.getByRole('button', { name: 'Скачать .md', exact: true }).click();
  const exported = await downloadPromise;
  expect(exported.suggestedFilename()).toMatch(/\.md$/);
  const exportedPath = await exported.path();
  expect(exportedPath).not.toBeNull();
  const body = await readFile(exportedPath!, 'utf8');
  expect(body).toContain('подтверждённый текст');
  expect(body).not.toContain('sutkn_browser_e2e');

  // A real page reload exercises IndexedDB + authenticated server restoration.
  // The provider boundary remains synthetic; no new capability is requested.
  page.once('dialog', (dialog) => dialog.accept());
  await page.reload();
  await page.getByRole('tab', { name: 'Live-транскрибация' }).click();
  const recovered = page.getByRole('region', { name: 'Live-транскрибация' });
  await recovered.getByRole('button', { name: 'Восстановить', exact: true }).click();
  await expect(recovered.getByText('подтверждённый текст', { exact: true })).toBeVisible();
  expect(capabilityRequests).toBe(1);
});

test('preparation stays fail-closed without external integrations', async ({
  page,
}) => {
  const navigation = await login(page);
  await openResultTranscriptions(page, navigation);

  const preparation = page.getByRole('region', {
    name: `Подготовка ${RESULT_PROJECT}`,
  });
  await expect(preparation).toBeVisible();

  const integrationRequests = trackExternalOrJobMutations(page);

  await expect(
    preparation.getByText(
      'Добавьте активный ключ ElevenLabs в настройках, чтобы создавать задачи.',
    ),
  ).toBeVisible();
  await expect(preparation.getByText('Google Drive не подключён.')).toBeVisible();
  await expect(
    preparation.getByRole('button', { name: 'Выбрать файлы Google Drive' }),
  ).toBeDisabled();
  await expect(
    preparation.getByRole('button', {
      name: 'Выбрать папку-источник Google Drive для задачи 1',
    }),
  ).toBeDisabled();
  const localFolderInput = preparation.getByLabel(
    'Выбрать папку с устройства для задачи 1',
  );
  await expect(localFolderInput).toHaveAttribute('type', 'file');
  await expect(localFolderInput).toHaveAttribute('multiple', '');
  await expect(localFolderInput).toHaveAttribute('webkitdirectory', '');
  await expect(
    preparation.getByRole('button', {
      name: 'Выбрать папку результата для задачи 1',
    }),
  ).toBeDisabled();

  const readiness = preparation.getByRole('status', {
    name: 'Готовность задач подготовки',
  });
  await expect(readiness).toContainText('Готово: 0 из 1');
  await expect(readiness).toContainText('Задача 1: выберите источник');

  const existingSourceSelect = preparation.getByLabel(
    'Существующий файл для задачи 1',
  );
  const existingSourceValue = await existingSourceSelect
    .locator('option')
    .filter({ hasText: 'browser-e2e-audio.mp3' })
    .getAttribute('value');
  if (!existingSourceValue) {
    throw new Error('Seeded browser E2E source option is missing');
  }
  await existingSourceSelect.selectOption(existingSourceValue);

  await expect(readiness).toContainText(
    'Задача 1: выберите папку результата',
  );
  await expect(
    preparation.getByRole('button', { name: 'Проверить задачи (1)' }),
  ).toBeDisabled();
  await expect(preparation).toContainText(
    'Добавьте активный ключ ElevenLabs в настройках',
  );
  expect(integrationRequests).toEqual([]);
});

test('transcript maintenance stays fail-closed without Google authority', async ({
  page,
}) => {
  const navigation = await login(page);
  const maintenanceMutations: string[] = [];
  page.on('request', (request) => {
    const url = new URL(request.url());
    if (
      request.method() !== 'GET' &&
      url.pathname.startsWith('/api/transcript-maintenance/')
    ) {
      maintenanceMutations.push(`${request.method()} ${url.pathname}`);
    }
  });

  await navigation
    .getByRole('button', { name: 'Транскрибации', exact: true })
    .click();
  await expect(page).toHaveURL(/\/transcriptions$/);
  await page
    .getByRole('tab', { name: 'Обслуживание', exact: true })
    .click();

  const maintenance = page.getByRole('region', {
    name: 'Проверка и обновление Google Docs',
  });
  await expect(maintenance).toBeVisible();
  await expect(maintenance).toContainText(
    'Выберите один документ или папку с подпапками.',
  );
  await expect(
    maintenance.getByText(
      'Сначала подключите Google Drive.',
    ),
  ).toBeVisible();
  for (const operationName of [
    'Привести документы к текущему формату',
    'Учесть готовые документы в Studio',
  ]) {
    const operation = page.getByRole('region', { name: operationName });
    const targetMode = operation.getByRole('combobox', {
      name: 'Что обработать',
    });
    await expect(targetMode).toBeDisabled();
    await expect(targetMode).toHaveValue('folder_tree');
    await expect(
      targetMode.getByRole('option', { name: 'Папка и все подпапки' }),
    ).toHaveCount(1);
    await expect(
      targetMode.getByRole('option', {
        name: 'Один конкретный Google Doc',
      }),
    ).toHaveCount(1);
    await expect(
      operation.getByRole('button', { name: 'Выбрать папку' }),
    ).toBeDisabled();
    await expect(
      operation.getByRole('button', { name: 'Проверить документы' }),
    ).toBeDisabled();
  }
  await expect(
    maintenance.getByRole('button', { name: /Подтвердить/ }),
  ).toHaveCount(0);
  expect(maintenanceMutations).toEqual([]);
});

test('uncertain provider result can be explicitly closed without another provider call', async ({
  page,
}) => {
  const navigation = await login(page);
  await openResultTranscriptions(page, navigation);

  const currentJobs = page.getByLabel('Текущие транскрибации');
  const jobCard = currentJobs
    .locator('article.source-card')
    .filter({ hasText: UNCERTAIN_JOB })
    .first();
  await expect(jobCard.getByText('Статус: Ошибка')).toBeVisible();
  await expect(jobCard).toContainText(
    'Эта задача требует решения и сохранена после очистки истории.',
  );
  await expect(
    jobCard.getByRole('button', { name: 'Убрать в историю', exact: true }),
  ).toHaveCount(0);
  const uncertainJobId = await jobCard.getAttribute('data-job-id');
  expect(uncertainJobId).toMatch(/^[0-9a-f-]{36}$/);

  const uncertainDetails = jobCard.locator('details.attention-job-details');
  await expect(uncertainDetails).not.toHaveAttribute('open', '');
  await uncertainDetails.locator(':scope > summary').click();
  await expect(jobCard.getByRole('button', { name: 'Открыть' })).toBeVisible();

  const integrationRequests = trackExternalOrJobMutations(page);
  const retryResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      response.url().endsWith(`/api/jobs/${uncertainJobId}/retry`),
  );
  const reconciliationResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      response.url().endsWith(
        `/api/jobs/${uncertainJobId}/output-reconciliation`,
      ),
  );
  await jobCard.getByRole('button', { name: 'Открыть' }).click();

  const retryResponse = await retryResponsePromise;
  expect(retryResponse.status()).toBe(200);
  const retry = await retryResponse.json();
  expect(retry).toMatchObject({
    job_status: 'failed',
    available: false,
    reason: 'provider_outcome_uncertain',
    attempt_count: 1,
    missing_output_count: 1,
    retry_safe_source_count: 0,
  });

  const reconciliationResponse = await reconciliationResponsePromise;
  expect(reconciliationResponse.status()).toBe(200);
  const reconciliation = await reconciliationResponse.json();
  expect(reconciliation).toMatchObject({
    job_status: 'failed',
    available: false,
    counts: {
      reconciliation_required: 0,
      resolved: 0,
      conflict: 0,
    },
  });

  await expect(jobCard.getByRole('heading', { name: 'Результаты' })).toBeVisible();
  await expect(jobCard.getByText('Результаты пока не созданы.')).toBeVisible();
  await expect(jobCard.getByText('Статус обработки: Ошибка')).toBeVisible();

  const retryAction = jobCard.getByRole('region', {
    name: 'Действия после ошибки',
  });
  await expect(retryAction).toContainText(
    'Повтор недоступен: результат внешнего вызова не определён',
  );
  await expect(
    retryAction.getByRole('button', {
      name: 'Повторить безопасную обработку',
    }),
  ).toHaveCount(0);
  await expect(
    jobCard.getByRole('region', { name: 'Проверка результата в Google Drive' }),
  ).toHaveCount(0);
  await expect(
    jobCard.getByRole('button', {
      name: 'Проверить созданный документ в Google Drive',
    }),
  ).toHaveCount(0);
  expect(integrationRequests).toEqual([]);
  await uncertainDetails.locator(':scope > summary').click();
  await expect(uncertainDetails).not.toHaveAttribute('open', '');
  const closeError = jobCard.getByRole('button', { name: 'Закрыть ошибку и убрать в историю' });
  await expect(closeError).toBeVisible();
  await expect(jobCard.getByRole('button', { name: 'Проверить результат ещё раз' })).toHaveCount(0);
  await expect(jobCard.getByText(/Отсутствие документа не подтверждено/)).toBeVisible();
  page.once('dialog', async (dialog) => {
    expect(dialog.message()).toContain('мог уже списать средства');
    await dialog.dismiss();
  });
  await closeError.click();
  expect(integrationRequests).toEqual([]);
  page.once('dialog', (dialog) => dialog.accept());
  const resolutionResponse = page.waitForResponse((response) => response.request().method() === 'POST' && response.url().endsWith(`/api/jobs/${uncertainJobId}/attention-resolution`));
  await closeError.click();
  expect((await resolutionResponse).status()).toBe(200);
  await expect(jobCard).toHaveCount(0);
  const readback = await page.request.get(`/api/jobs/${uncertainJobId}`);
  expect(readback.status()).toBe(200);
  expect(await readback.json()).toMatchObject({
    status: 'failed',
    history_attention_resolution: 'acknowledged_no_result',
    history_attention_resolved_at: expect.any(String),
    terminal_dismissed_at: expect.any(String),
  });
  expect(integrationRequests.filter((request) => request.startsWith('POST'))).toEqual([
    `POST http://127.0.0.1:4173/api/jobs/${uncertainJobId}/attention-resolution`,
  ]);
});

test('unresolved output reconciliation waits for an explicit safe action', async ({
  page,
}) => {
  const navigation = await login(page);
  await openResultTranscriptions(page, navigation);

  const currentJobs = page.getByLabel('Текущие транскрибации');
  const jobCard = currentJobs
    .locator('article.source-card')
    .filter({ hasText: RECONCILIATION_JOB })
    .first();
  await expect(jobCard.getByText('Статус: Ошибка')).toBeVisible();
  await expect(jobCard).toContainText(
    'Эта задача требует решения и сохранена после очистки истории.',
  );
  await expect(
    jobCard.getByRole('button', { name: 'Убрать в историю', exact: true }),
  ).toHaveCount(0);
  const reconciliationJobId = await jobCard.getAttribute('data-job-id');
  expect(reconciliationJobId).toMatch(/^[0-9a-f-]{36}$/);

  const reconciliationDetails = jobCard.locator('details.attention-job-details');
  await expect(reconciliationDetails).not.toHaveAttribute('open', '');
  await reconciliationDetails.locator(':scope > summary').click();
  await expect(jobCard.getByRole('button', { name: 'Открыть' })).toBeVisible();

  const integrationRequests = trackExternalOrJobMutations(page);
  const retryResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      response.url().endsWith(`/api/jobs/${reconciliationJobId}/retry`),
  );
  const reconciliationResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      response.url().endsWith(
        `/api/jobs/${reconciliationJobId}/output-reconciliation`,
      ),
  );
  await jobCard.getByRole('button', { name: 'Открыть' }).click();

  const retryResponse = await retryResponsePromise;
  expect(retryResponse.status()).toBe(200);
  const retry = await retryResponse.json();
  expect(retry).toMatchObject({
    job_status: 'failed',
    available: false,
    reason: 'output_reconciliation_required',
    attempt_count: 1,
    missing_output_count: 1,
    retry_safe_source_count: 0,
  });

  const reconciliationResponse = await reconciliationResponsePromise;
  expect(reconciliationResponse.status()).toBe(200);
  const reconciliation = await reconciliationResponse.json();
  expect(reconciliation).toMatchObject({
    job_status: 'failed',
    available: true,
    counts: {
      reconciliation_required: 1,
      resolved: 0,
      conflict: 0,
    },
    cases: [
      {
        status: 'reconciliation_required',
        reason: 'google_docs_timeout',
        resolved: false,
      },
    ],
  });
  const reconciliationJson = JSON.stringify(reconciliation);
  expect(reconciliationJson).not.toContain(RECONCILIATION_TOKEN);
  expect(reconciliationJson).not.toContain('Browser E2E pending document');
  expect(reconciliationJson).not.toContain('browser-e2e-folder');

  await expect(jobCard.getByRole('heading', { name: 'Результаты' })).toBeVisible();
  const reconciliationNotice = jobCard.locator('.attention-resolution-controls');
  await expect(
    reconciliationNotice.getByRole('button', {
      name: 'Проверить результат ещё раз',
    }),
  ).toBeVisible();

  const retryAction = jobCard.getByRole('region', {
    name: 'Действия после ошибки',
  });
  await expect(retryAction).toContainText(
    'Требуется проверка созданного документа',
  );
  await expect(
    retryAction.getByRole('button', {
      name: 'Повторить безопасную обработку',
    }),
  ).toHaveCount(0);
  expect(integrationRequests).toEqual([]);
});

test('progress refresh keeps the last confirmed checkpoint after a temporary failure', async ({
  page,
}) => {
  const navigation = await login(page);

  const integrationRequests = trackExternalOrJobMutations(page);
  const initialProgressResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      isJobProgressUrl(response.url()),
  );
  await openResultTranscriptions(page, navigation);

  const initialProgressResponse = await initialProgressResponsePromise;
  expect(initialProgressResponse.status()).toBe(200);
  const initialProgressPayload = await initialProgressResponse.json();
  const processingProgress = initialProgressPayload.jobs.find(
    (job: { job_status?: string }) => job.job_status === 'processing',
  );
  expect(processingProgress).toMatchObject({
    job_status: 'processing',
    current_stage: 'provider_processing',
  });
  expect(processingProgress.job_id).toMatch(/^[0-9a-f-]{36}$/);

  const progress = page.getByRole('region', {
    name: `Прогресс задачи ${processingProgress.job_id}`,
  });
  await expect(
    progress.getByText('Распознавание речи').locator('..'),
  ).toContainText('Выполняется');
  await expect(
    progress.getByText('Сохранение документа').locator('..'),
  ).toContainText('Ожидает');

  let failedRefreshes = 0;
  await page.route((url) => isJobProgressUrl(url.href), async (route) => {
    if (route.request().method() !== 'GET') {
      await route.continue();
      return;
    }
    failedRefreshes += 1;
    await route.fulfill({
      status: 503,
      contentType: 'application/json',
      body: JSON.stringify({ detail: 'temporary_progress_unavailable' }),
    });
  });
  const failedProgressResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      isJobProgressUrl(response.url()) &&
      response.status() === 503,
  );

  const failedProgressResponse = await failedProgressResponsePromise;
  expect(failedProgressResponse.status()).toBe(503);
  expect(failedRefreshes).toBe(1);
  await expect(
    progress.getByText(
      'Не удалось обновить прогресс; показан последний подтверждённый статус.',
    ),
  ).toBeVisible();
  await expect(
    progress.getByText('Подготовка источника').locator('..'),
  ).toContainText('Готово');
  await expect(
    progress.getByText('Распознавание речи').locator('..'),
  ).toContainText('Выполняется');
  await expect(
    progress.getByText('Сохранение документа').locator('..'),
  ).toContainText('Ожидает');
  await expect(progress.getByText('Готово файлов: 0 из 1')).toBeVisible();
  expect(integrationRequests).toEqual([]);
});

test('processing cancellation records a request without claiming completion', async ({
  page,
}) => {
  const navigation = await login(page);

  const integrationRequests = trackExternalOrJobMutations(page);
  const progressResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      isJobProgressUrl(response.url()),
  );
  await openResultTranscriptions(page, navigation);

  const progressResponse = await progressResponsePromise;
  expect(progressResponse.status()).toBe(200);
  const progressPayload = await progressResponse.json();
  const processingProgress = progressPayload.jobs.find(
    (job: { job_status?: string }) => job.job_status === 'processing',
  );
  expect(processingProgress).toMatchObject({
    job_status: 'processing',
    tracking_precision: 'checkpoint',
    completed_source_count: 0,
    total_source_count: 1,
    active_source_position: 0,
    current_stage: 'provider_processing',
    sources: [
      {
        position: 0,
        name: 'browser-e2e-audio.mp3',
        status: 'processing',
        stages: [
          {
            key: 'preparation',
            status: 'completed',
            applicability: 'required',
          },
          {
            key: 'audio_extraction',
            status: 'not_applicable',
            applicability: 'not_applicable',
          },
          {
            key: 'splitting',
            status: 'completed',
            applicability: 'conditional',
          },
          {
            key: 'provider_processing',
            status: 'active',
            applicability: 'required',
          },
          {
            key: 'part_merge',
            status: 'pending',
            applicability: 'conditional',
          },
          {
            key: 'google_docs_output',
            status: 'pending',
            applicability: 'required',
          },
        ],
      },
    ],
  });
  expect(processingProgress.job_id).toMatch(/^[0-9a-f-]{36}$/);
  expect(JSON.stringify(processingProgress)).not.toContain(
    'browser-e2e-worker',
  );

  const progress = page.getByRole('region', {
    name: `Прогресс задачи ${processingProgress.job_id}`,
  });
  await expect(progress.getByText('Готово файлов: 0 из 1')).toBeVisible();
  await expect(
    progress.getByText('Подготовка источника').locator('..'),
  ).toContainText('Готово');
  await expect(
    progress.getByText('Извлечение аудио').locator('..'),
  ).toContainText('Не требуется');
  await expect(
    progress
      .getByText('Разбиение на части (при необходимости)')
      .locator('..'),
  ).toContainText('Проверено');
  await expect(
    progress.getByText('Распознавание речи').locator('..'),
  ).toContainText('Выполняется');
  await expect(
    progress.getByText('Сохранение документа').locator('..'),
  ).toContainText('Ожидает');

  const currentJobs = page.getByRole('region', { name: 'Текущие транскрибации' });
  const processingCard = currentJobs
    .locator('article.source-card')
    .filter({ hasText: PROCESSING_CANCELLATION_JOB })
    .first();
  await expect(processingCard.getByText('Статус: Обрабатывается')).toBeVisible();

  const cancelResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      response.url().endsWith('/cancel'),
  );
  await processingCard
    .getByRole('button', { name: 'Запросить отмену' })
    .click();

  const cancelResponse = await cancelResponsePromise;
  expect(cancelResponse.status()).toBe(200);
  const cancellationRequested = await cancelResponse.json();
  expect(cancellationRequested).toMatchObject({
    status: 'processing',
    attempt_count: 1,
    cancelled_at: null,
    finished_at: null,
  });
  expect(String(cancellationRequested.cancel_requested_at ?? '')).toMatch(
    /^\d{4}-\d{2}-\d{2}T/,
  );

  await expect(
    page.getByText(
      'Запрос отмены отправлен. Уже созданные результаты останутся доступны.',
    ),
  ).toBeVisible();
  await expect(processingCard.getByText('Статус: Обрабатывается')).toBeVisible();
  await expect(
    processingCard.getByText('Отмена запрошена', { exact: true }),
  ).toBeVisible();
  await expect(
    processingCard.getByRole('button', { name: 'Запросить отмену' }),
  ).toHaveCount(0);

  expect(integrationRequests).toHaveLength(1);
  expect(integrationRequests[0]).toMatch(
    /^POST http:\/\/127\.0\.0\.1:4173\/api\/jobs\/[0-9a-f-]{36}\/cancel$/,
  );
});

test('queued cancellation performs one bounded API mutation', async ({
  page,
}) => {
  const navigation = await login(page);

  const integrationRequests = trackExternalOrJobMutations(page);
  const progressResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      isJobProgressUrl(response.url()),
  );
  await openResultTranscriptions(page, navigation);

  const progressResponse = await progressResponsePromise;
  expect(progressResponse.status()).toBe(200);
  const progressPayload = await progressResponse.json();
  const queuedProgress = progressPayload.jobs.find(
    (job: { job_status?: string }) => job.job_status === 'queued',
  );
  expect(queuedProgress).toMatchObject({
    job_status: 'queued',
    tracking_precision: 'checkpoint',
    completed_source_count: 0,
    total_source_count: 1,
    active_source_position: null,
    current_stage: null,
    sources: [
      {
        position: 0,
        name: 'browser-e2e-audio.mp3',
        status: 'queued',
        stages: [
          {
            key: 'preparation',
            status: 'pending',
            applicability: 'required',
          },
          {
            key: 'audio_extraction',
            status: 'not_applicable',
            applicability: 'not_applicable',
          },
          {
            key: 'splitting',
            status: 'pending',
            applicability: 'conditional',
          },
          {
            key: 'provider_processing',
            status: 'pending',
            applicability: 'required',
          },
          {
            key: 'part_merge',
            status: 'pending',
            applicability: 'conditional',
          },
          {
            key: 'google_docs_output',
            status: 'pending',
            applicability: 'required',
          },
        ],
      },
    ],
  });
  expect(queuedProgress.job_id).toMatch(/^[0-9a-f-]{36}$/);

  const progress = page.getByRole('region', {
    name: `Прогресс задачи ${queuedProgress.job_id}`,
  });
  await expect(progress.getByText('Готово файлов: 0 из 1')).toBeVisible();
  await expect(
    progress.getByText('Подготовка источника').locator('..'),
  ).toContainText('Ожидает');
  await expect(
    progress.getByText('Извлечение аудио').locator('..'),
  ).toContainText('Не требуется');
  await expect(
    progress.getByText('Распознавание речи').locator('..'),
  ).toContainText('Ожидает');
  await expect(
    progress.getByText('Сохранение документа').locator('..'),
  ).toContainText('Ожидает');
  await expect(progress.getByText('Выполняется', { exact: true })).toHaveCount(
    0,
  );
  await expect(progress.getByText('Готово', { exact: true })).toHaveCount(0);
  await expect(progress.getByText('Проверено', { exact: true })).toHaveCount(0);

  const currentJobs = page.getByRole('region', { name: 'Текущие транскрибации' });
  const queuedCard = currentJobs
    .locator('article.source-card')
    .filter({ hasText: QUEUED_CANCELLATION_JOB })
    .first();
  await expect(queuedCard.getByText('Статус: В очереди')).toBeVisible();

  const cancelResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      response.url().endsWith('/cancel'),
  );
  await queuedCard.getByRole('button', { name: 'Отменить' }).click();

  const cancelResponse = await cancelResponsePromise;
  expect(cancelResponse.status()).toBe(200);
  const cancelled = await cancelResponse.json();
  expect(cancelled).toMatchObject({
    status: 'cancelled',
    attempt_count: 0,
    started_at: null,
    cancel_requested_at: null,
  });
  expect(String(cancelled.cancelled_at ?? '')).toMatch(
    /^\d{4}-\d{2}-\d{2}T/,
  );

  await expect(
    page.getByText(
      'Запрос отмены отправлен. Уже созданные результаты останутся доступны.',
    ),
  ).toBeVisible();
  await expect(
    queuedCard.getByText('Статус: Отменена'),
  ).toBeVisible();
  await expect(
    queuedCard.getByRole('button', { name: 'Отменить' }),
  ).toHaveCount(0);
  await expect(
    queuedCard.getByRole('button', { name: 'Убрать в историю' }),
  ).toBeVisible();
  await expect(currentJobs).toContainText(PROCESSING_CANCELLATION_JOB);

  const dismissResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      response.url().endsWith('/dismiss'),
  );
  await queuedCard
    .getByRole('button', { name: 'Убрать в историю' })
    .click();
  const dismissResponse = await dismissResponsePromise;
  expect(dismissResponse.status()).toBe(200);
  const dismissed = await dismissResponse.json();
  expect(String(dismissed.terminal_dismissed_at ?? '')).toMatch(
    /^\d{4}-\d{2}-\d{2}T/,
  );
  await expect(
    currentJobs
      .locator('article.source-card')
      .filter({ hasText: QUEUED_CANCELLATION_JOB }),
  ).toHaveCount(0);

  await page
    .locator('details.recent-jobs')
    .getByText(/^Недавние транскрибации · \d+$/)
    .click();
  const cancelledCard = page
    .locator('article.source-card')
    .filter({ hasText: QUEUED_CANCELLATION_JOB })
    .first();
  await expect(cancelledCard.getByText('Статус: Отменена')).toBeVisible();
  await expect(
    cancelledCard.getByRole('button', { name: 'Отменить' }),
  ).toHaveCount(0);

  expect(integrationRequests).toHaveLength(2);
  expect(integrationRequests[0]).toMatch(
    /^POST http:\/\/127\.0\.0\.1:4173\/api\/jobs\/[0-9a-f-]{36}\/cancel$/,
  );
  expect(integrationRequests[1]).toMatch(
    /^POST http:\/\/127\.0\.0\.1:4173\/api\/jobs\/[0-9a-f-]{36}\/dismiss$/,
  );
});

test('retry-safe provider rejection performs one explicit requeue mutation', async ({
  page,
}) => {
  const navigation = await login(page);
  await openResultTranscriptions(page, navigation);

  const recentJobs = page.locator('details.recent-jobs');
  await recentJobs.getByText(/^Недавние транскрибации · \d+$/).click();
  const retryCard = recentJobs
    .locator('article.source-card')
    .filter({ hasText: RETRY_SAFE_JOB })
    .first();
  await expect(retryCard.getByText('Статус: Ошибка')).toBeVisible();
  const retryJobId = await retryCard.getAttribute('data-job-id');
  expect(retryJobId).toMatch(/^[0-9a-f-]{36}$/);

  const integrationRequests = trackExternalOrJobMutations(page);
  const retryReadinessResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'GET' &&
      response.url().endsWith(`/api/jobs/${retryJobId}/retry`),
  );
  await retryCard.getByRole('button', { name: 'Открыть' }).click();

  const retryReadinessResponse = await retryReadinessResponsePromise;
  expect(retryReadinessResponse.status()).toBe(200);
  const retryReadiness = await retryReadinessResponse.json();
  expect(retryReadiness).toMatchObject({
    job_status: 'failed',
    available: true,
    reason: 'available',
    attempt_count: 1,
    max_attempts: 3,
    missing_output_count: 1,
    retry_safe_source_count: 1,
  });

  const retryAction = retryCard.getByRole('region', {
    name: 'Действия после ошибки',
  });
  const retryButton = retryAction.getByRole('button', {
    name: 'Повторить безопасную обработку',
  });
  await expect(retryButton).toBeVisible();
  expect(integrationRequests).toEqual([]);

  const retryMutationResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      response.url().endsWith(`/api/jobs/${retryJobId}/retry`),
  );
  await retryButton.click();

  const retryMutationResponse = await retryMutationResponsePromise;
  expect(retryMutationResponse.status()).toBe(200);
  const queuedRetry = await retryMutationResponse.json();
  expect(queuedRetry).toMatchObject({
    job_status: 'queued',
    available: true,
    reason: 'available',
    attempt_count: 1,
    max_attempts: 3,
    missing_output_count: 0,
    retry_safe_source_count: 0,
  });

  const currentJobs = page.getByRole('region', { name: 'Текущие транскрибации' });
  const queuedRetryCard = currentJobs
    .locator('article.source-card')
    .filter({ hasText: RETRY_SAFE_JOB })
    .first();
  await expect(queuedRetryCard.getByText('Статус: В очереди')).toBeVisible();
  await expect(
    queuedRetryCard.getByRole('button', {
      name: 'Повторить безопасную обработку',
    }),
  ).toHaveCount(0);
  await expect(
    recentJobs
      .locator('article.source-card')
      .filter({ hasText: RETRY_SAFE_JOB }),
  ).toHaveCount(0);

  expect(integrationRequests).toHaveLength(1);
  expect(integrationRequests[0]).toMatch(
    /^POST http:\/\/127\.0\.0\.1:4173\/api\/jobs\/[0-9a-f-]{36}\/retry$/,
  );
});
