FROM node:22-slim
WORKDIR /app
COPY package*.json ./
RUN npm install --omit=dev
COPY client ./client
RUN npm --prefix client install && npm --prefix client run build && rm -rf client/node_modules
COPY server ./server
ENV PORT=8787
EXPOSE 8787
CMD ["node", "server/index.js"]
