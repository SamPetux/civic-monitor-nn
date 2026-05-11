import Link from 'next/link'

const links = [
  { href: '/',        label: 'Карта',   key: 'map' },
  { href: '/topics',  label: 'Темы',    key: 'topics' },
  { href: '/users',   label: 'Авторы',  key: 'users' },
]

export default function Navbar({ active }: { active: string }) {
  return (
    <header className="bg-[#1e3a5f] text-white shadow-md">
      <div className="max-w-7xl mx-auto px-4 h-14 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-lg font-bold tracking-tight">Civic Monitor</span>
          <span className="text-xs text-blue-300 bg-blue-900/40 px-2 py-0.5 rounded-full">НН</span>
        </div>
        <nav className="flex gap-1">
          {links.map(l => (
            <Link key={l.key} href={l.href}
              className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors
                ${active === l.key ? 'bg-white/20 text-white' : 'text-blue-200 hover:bg-white/10 hover:text-white'}`}>
              {l.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  )
}