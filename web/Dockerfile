FROM node:20-alpine AS build

ARG VITE_VALO_EDITION=community
ENV VITE_VALO_EDITION=${VITE_VALO_EDITION}

WORKDIR /web
COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /web/dist /usr/share/nginx/html

EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
