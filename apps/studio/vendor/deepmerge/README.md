# Локальный security patch deepmerge

Upstream: `deepmerge@4.3.1`, опубликованный `dist/cjs.js`, SHA256 `2e5160f84a1141bd927264afe4d15766f1e6cf07daef182b37ff53fea121de7d`. Лицензия сохранена в [LICENSE](LICENSE).

GHSA-gcqx-w48m-w2h4 / CVE-2026-93753: обычное присваивание `destination[key]` при копировании target и при merge source могло вызвать унаследованный setter `__proto__`. Все три записи используют `Object.defineProperty` с обычными enumerable/writable/configurable data properties. Содержимое свойства сохраняется без изменения prototype результата; array/custom merge и symbol keys сохраняют upstream API.

Пакет имеет собственную identity `@voiceops-studio/deepmerge@4.3.1-voiceops.1` и подставляется через корневой npm override. Это исходный проверяемый патч, не postinstall mutation: `npm ci --ignore-scripts` использует тот же код. Единственный текущий потребитель — `@rollup/plugin-node-resolve`, клонирующий статические defaults при сборке PWA. Runtime приложения этот пакет не включает.

Аннотация CommonJS global и optional catch binding адаптируют upstream файл к действующему ESLint проекта; application lint rules и gates не отключаются.

Обновление: при появлении upstream fix сверить обе copy/merge ветки и malicious/compatibility regressions в `src/deepmergeBoundary.test.ts`, затем заменить override и удалить этот fork только вместе с обновлённым lock. Исходный upstream код и лицензия учитываются как vendored область, отдельно от приложения.
