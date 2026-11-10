async function request(path, options) {
  let response
  try {
    response = await fetch(`/api${path}`, options)
  } catch {
    throw new Error('无法连接检测服务，请确认后端已启动。')
  }
  const body = await response.json().catch(() => null)
  if (!response.ok || !body) {
    const detail = typeof body?.detail === 'string' ? body.detail : '检测服务暂不可用，请稍后重试。'
    throw Object.assign(new Error(detail), { status: response.status })
  }
  return body
}

export const getSamples = () => request('/samples')
export const getTask = (id) => request(`/tasks/${id}`)

export function submitTask(source) {
  const form = new FormData()
  if (source.file) form.append('file', source.file)
  else form.append('sample_id', source.id)
  return request('/tasks', { method: 'POST', body: form })
}
