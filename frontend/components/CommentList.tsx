import type { Comment } from '@/lib/types'

const SENT_STYLE: Record<string, string> = {
  negative: 'border-l-red-400 bg-red-50',
  neutral:  'border-l-gray-300 bg-gray-50',
  positive: 'border-l-green-400 bg-green-50',
}
const SENT_LABEL: Record<string, string> = {
  negative: 'негатив', neutral: 'нейтрал', positive: 'позитив',
}

export default function CommentList({ comments }: { comments: Comment[] }) {
  if (!comments.length) return <p className="text-gray-400 text-sm py-4 text-center">Нет комментариев</p>

  return (
    <div className="space-y-2">
      {comments.map((c, i) => (
        <div key={i} className={`border-l-4 pl-3 pr-2 py-2 rounded-r-lg ${SENT_STYLE[c.sentiment]}`}>
          <div className="flex items-center gap-2 mb-1">
            <a href={c.user_url ?? '#'} target="_blank" rel="noreferrer"
               className="text-xs font-medium text-indigo-600 hover:underline">
              {c.author}
            </a>
            <span className="text-xs text-gray-400">·</span>
            <a href={c.group_url ?? '#'} target="_blank" rel="noreferrer"
               className="text-xs text-gray-400 hover:underline truncate max-w-[120px]">
              {c.group}
            </a>
            <span className="ml-auto text-xs text-gray-400">{c.created_at.slice(0, 16).replace('T', ' ')}</span>
          </div>
          <p className="text-sm text-gray-700 leading-snug line-clamp-3">{c.text}</p>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs text-gray-400">{SENT_LABEL[c.sentiment]}</span>
            {c.comment_url && (
              <a href={c.comment_url} target="_blank" rel="noreferrer"
                 className="text-xs text-indigo-400 hover:underline ml-auto">→ VK</a>
            )}
          </div>
        </div>
      ))}
    </div>
  )
}