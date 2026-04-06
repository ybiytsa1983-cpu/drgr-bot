import { useState } from 'react';
import ArticleGeneratorPage from './pages/ArticleGeneratorPage';
import AutomationPage from './pages/AutomationPage';
import BotControlsPage from './pages/BotControlsPage';
import EditorPage from './pages/EditorPage';
import VmChatPage from './pages/VmChatPage';
import VmDashboard from './pages/VmDashboard';
import VmSettingsPage from './pages/VmSettingsPage';

type Page =
  | 'dashboard'
  | 'chat'
  | 'editor'
  | 'articles'
  | 'bot'
  | 'automation'
  | 'settings';

const NAV_ITEMS: Array<{ id: Page; label: string; icon: string }> = [
  { id: 'dashboard', label: 'VM Статус', icon: '🖥️' },
  { id: 'chat', label: 'Чат', icon: '💬' },
  { id: 'editor', label: 'Редактор', icon: '✏️' },
  { id: 'articles', label: 'Статьи', icon: '📰' },
  { id: 'bot', label: 'Бот', icon: '🤖' },
  { id: 'automation', label: 'Автоматизация', icon: '⚡' },
  { id: 'settings', label: 'Настройки', icon: '⚙️' },
];

function PageContent({ page }: { page: Page }) {
  switch (page) {
    case 'dashboard':
      return <VmDashboard />;
    case 'chat':
      return <VmChatPage />;
    case 'editor':
      return <EditorPage />;
    case 'articles':
      return <ArticleGeneratorPage />;
    case 'bot':
      return <BotControlsPage />;
    case 'automation':
      return <AutomationPage />;
    case 'settings':
      return <VmSettingsPage />;
    default:
      return <VmDashboard />;
  }
}

export default function App() {
  const [page, setPage] = useState<Page>('dashboard');

  return (
    <div className="flex min-h-screen bg-[#0d1117] text-slate-100">
      {/* Sidebar */}
      <nav className="flex w-14 flex-col items-center gap-1 border-r border-slate-800 bg-[#161b22] py-3 md:w-48 md:items-stretch md:px-2">
        <div className="mb-3 hidden text-center text-sm font-bold text-emerald-400 md:block">
          DRGR Local Comet
        </div>
        <div className="mb-3 text-center text-sm font-bold text-emerald-400 md:hidden">
          D
        </div>
        {NAV_ITEMS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setPage(item.id)}
            className={`flex items-center gap-2 rounded-md px-2 py-2 text-left text-sm transition-colors ${
              page === item.id
                ? 'bg-slate-700/60 text-white'
                : 'text-slate-400 hover:bg-slate-800 hover:text-slate-200'
            }`}
            title={item.label}
          >
            <span className="text-base">{item.icon}</span>
            <span className="hidden md:inline">{item.label}</span>
          </button>
        ))}
      </nav>

      {/* Main content */}
      <div className="flex-1 overflow-y-auto">
        <PageContent page={page} />
      </div>
    </div>
  );
}
