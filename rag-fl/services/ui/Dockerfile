FROM node:20-alpine
WORKDIR /app

# Install dependencies first (layer cache)
COPY package*.json ./
RUN npm install

# Copy source
COPY . .

EXPOSE 3001

# next dev reads NEXT_PUBLIC_* from process.env at startup — works with docker-compose environment:
CMD ["npm", "run", "dev"]
