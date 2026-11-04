# Update each reviewable tag and its multi-platform index digest together.
FROM node:22-alpine@sha256:16e22a550f3863206a3f701448c45f7912c6896a62de43add43bb9c86130c3e2 AS build
ARG STUDIO_RELEASE_VERSION=unknown
ARG STUDIO_COMMIT_SHA=unknown
ARG STUDIO_COMPONENT=web
ENV STUDIO_RUNTIME_RELEASE_VERSION=${STUDIO_RELEASE_VERSION} \
    STUDIO_RUNTIME_COMMIT_SHA=${STUDIO_COMMIT_SHA} \
    STUDIO_RUNTIME_BUILD_ID=${STUDIO_COMPONENT}-${STUDIO_COMMIT_SHA}
WORKDIR /app
COPY package.json package-lock.json ./
COPY vendor ./vendor
RUN npm ci
COPY . .
RUN npm run build
FROM nginx:1.28.3-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
