import '@testing-library/jest-dom/vitest'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, cleanup } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Rooms } from '../src/features/rooms/Rooms'
import { api } from '../src/api/client'
vi.mock('../src/api/client', () => ({ api: { rooms: vi.fn(), avatars: vi.fn(), voices: vi.fn(), products: vi.fn(), createRoom: vi.fn(), updateRoom: vi.fn() } }))
const room = { roomId: 'r_1', name: 'Room', avatarId: 'a_1', voiceId: 'v_1', systemPrompt: 'Original', activeProductId: 'p_1', knowledgeBaseId: 'kb_1' }
function mount() { return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><Rooms onConsole={vi.fn()} /></QueryClientProvider>) }
beforeEach(() => {
  vi.mocked(api.rooms).mockResolvedValue([room])
  vi.mocked(api.avatars).mockResolvedValue([{ avatarId: 'a_1', name: 'Avatar', engine: 'MOCK', status: 'CREATED' }])
  vi.mocked(api.voices).mockResolvedValue([{ voiceId: 'v_1', name: 'Voice', provider: 'MOCK', providerVoiceId: 'mock' }])
  vi.mocked(api.products).mockResolvedValue([{ productId: 'p_1', name: 'Product', description: '', price: 1, currency: 'CNY', stock: 1, sizes: [] }])
  vi.mocked(api.createRoom).mockResolvedValue(room)
  vi.mocked(api.updateRoom).mockResolvedValue(room)
})
afterEach(() => { cleanup(); vi.clearAllMocks() })
it('creates a room with selected product, prompt and knowledge base', async () => {
  vi.mocked(api.rooms).mockResolvedValue([])
  mount()
  await screen.findByRole('option', { name: 'Product' })
  fireEvent.change(screen.getByLabelText('直播间名称'), { target: { value: 'New' } })
  fireEvent.change(screen.getByLabelText('Avatar'), { target: { value: 'a_1' } })
  fireEvent.change(screen.getByLabelText('Voice'), { target: { value: 'v_1' } })
  fireEvent.change(screen.getByLabelText('当前直播商品'), { target: { value: 'p_1' } })
  fireEvent.change(screen.getByLabelText('KnowledgeBase ID'), { target: { value: 'kb_1' } })
  fireEvent.change(screen.getByLabelText('System Prompt'), { target: { value: 'Prompt' } })
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(api.createRoom).toHaveBeenCalledWith({ name: 'New', avatarId: 'a_1', voiceId: 'v_1', activeProductId: 'p_1', knowledgeBaseId: 'kb_1', systemPrompt: 'Prompt' }))
})
it('loads and updates the existing active product', async () => {
  mount()
  fireEvent.click(await screen.findByRole('button', { name: '编辑' }))
  expect(screen.getByLabelText('当前直播商品')).toHaveValue('p_1')
  fireEvent.click(screen.getByRole('button', { name: '保存' }))
  await waitFor(() => expect(api.updateRoom).toHaveBeenCalledWith('r_1', expect.objectContaining({ activeProductId: 'p_1', knowledgeBaseId: 'kb_1', systemPrompt: 'Original' })))
})
