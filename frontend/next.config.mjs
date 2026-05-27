/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  // Проксируем /api/* на бэкенд — клиент всегда вызывает относительные пути
  async rewrites() {
    const target = process.env.API_INTERNAL_URL ?? 'http://localhost:8000'
    return [{ source: '/api/:path*', destination: `${target}/api/:path*` }]
  },
}
export default nextConfig