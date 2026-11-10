<script setup>
import { computed, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { getSamples, getTask, submitTask } from './api'

const modes = [
  { id: 'image', label: '图片检测', format: 'JPEG、PNG · 最大 20 MiB', accept: '.jpg,.jpeg,.png', limit: 20 },
  { id: 'video', label: '视频检测', format: 'MP4 · H.264 / AAC · 最大 500 MiB', accept: '.mp4', limit: 500 },
]
const stageLabels = {
  queued: '等待开始', reading: '读取素材', detecting: '识别目标',
  encoding: '生成标注文件', succeeded: '检测完成', failed: '检测失败',
}

const mode = ref(modes[0])
const samples = ref([])
const source = shallowRef(null)
const task = ref(null)
const submitting = ref(false)
const error = ref('')
const sampleError = ref('')
const originalError = ref(false)
const resultError = ref(false)
const busy = computed(() => submitting.value || ['queued', 'running'].includes(task.value?.status))
const currentSamples = computed(() => samples.value.filter((sample) => sample.kind === mode.value.id))
let timer
let disposed = false

onMounted(async () => {
  try {
    samples.value = await getSamples()
  } catch (failure) {
    sampleError.value = failure.message
  }
})

function choose(next) {
  // 上传预览使用临时浏览器地址，切换素材时及时释放。
  if (source.value?.file) URL.revokeObjectURL(source.value.url)
  source.value = next
  task.value = null
  error.value = ''
  originalError.value = false
  resultError.value = false
}

function switchMode(next) {
  if (busy.value || next.id === mode.value.id) return
  mode.value = next
  choose(null)
}

function selectFile(event) {
  const file = event.target.files[0]
  event.target.value = ''
  if (!file) return
  choose(null)
  const extension = file.name.toLowerCase().match(/\.[^.]+$/)?.[0]
  if (!mode.value.accept.split(',').includes(extension)) {
    error.value = `请选择符合格式的文件（${mode.value.format}）。`
  } else if (!file.size || file.size > mode.value.limit * 1024 ** 2) {
    error.value = file.size ? `文件超过 ${mode.value.limit} MiB。` : '上传文件为空。'
  } else {
    choose({ name: file.name, url: URL.createObjectURL(file), file })
  }
}

async function start() {
  if (!source.value || busy.value) return
  error.value = ''
  task.value = null
  resultError.value = false
  submitting.value = true
  try {
    const { id } = await submitTask(source.value)
    if (disposed) return
    task.value = { id, stage: 'queued', status: 'queued', progress: 0 }
    timer = setTimeout(() => poll(id), 1000)
  } catch (failure) {
    error.value = failure.message
  } finally {
    submitting.value = false
  }
}

async function poll(id) {
  try {
    const latest = await getTask(id)
    if (disposed) return
    task.value = latest
    error.value = latest.error || ''
  } catch (failure) {
    if (disposed) return
    if (failure.status === 404) {
      task.value = null
      error.value = '任务已失效，请重新提交。'
    } else {
      error.value = '暂时无法获取进度，正在重试。'
    }
  }
  // 等本次查询返回再安排下一次，避免网络慢时出现重叠查询。
  if (busy.value) timer = setTimeout(() => poll(id), 1000)
}

onUnmounted(() => {
  disposed = true
  clearTimeout(timer)
  if (source.value?.file) URL.revokeObjectURL(source.value.url)
})
</script>

<template>
  <main class="workspace">
    <header class="page-header">
      <div class="eyebrow"><span class="signal" /> 海事视觉 · 本地实训</div>
      <h1>船只对象识别系统</h1>
      <p>选择图片或视频，定位画面中的船只和其他目标。</p>
      <span class="model">YOLO26s / COCO</span>
    </header>

    <section class="controls" aria-label="选择素材">
      <div class="modes" role="group" aria-label="检测模式">
        <button v-for="item in modes" :key="item.id" type="button" :aria-pressed="item.id === mode.id"
                :disabled="busy" @click="switchMode(item)">{{ item.label }}</button>
      </div>
      <div class="source-bar">
        <label class="upload" :class="{ disabled: busy }">
          <span>选择本地文件</span>
          <input type="file" :accept="mode.accept" :disabled="busy" @change="selectFile" />
        </label>
        <select aria-label="内置样例" :value="source?.id || ''" :disabled="busy || !currentSamples.length"
                @change="choose(currentSamples.find((item) => item.id === $event.target.value) || null)">
          <option value="">选择内置样例</option>
          <option v-for="sample in currentSamples" :key="sample.id" :value="sample.id">{{ sample.name }}</option>
        </select>
        <button class="primary" type="button" :disabled="!source || busy" @click="start">
          {{ busy ? '检测处理中' : '开始检测' }}
        </button>
      </div>
      <p class="hint">{{ mode.format }}</p>
      <p v-if="sampleError" class="hint" role="status">样例加载失败。{{ sampleError }}</p>
      <p v-if="error" class="error" role="alert">{{ error }}</p>
      <div v-if="busy || task?.status === 'succeeded'" class="progress" role="status">
        <span>{{ submitting ? '正在提交素材' : stageLabels[task.stage] }}</span>
        <progress v-if="task?.progress != null" max="100" :value="task.progress" />
        <progress v-else max="100" />
        <span v-if="task?.progress != null">{{ task.progress }}%</span>
        <span v-else-if="task?.frames_processed">{{ task.frames_processed }} 帧</span>
      </div>
    </section>

    <div class="previews">
      <section class="panel">
        <header><h2>原始素材</h2><span>{{ source?.name }}</span></header>
        <div class="screen">
          <p v-if="!source">选择本地文件或内置样例</p>
          <p v-else-if="originalError">无法预览原始素材，请检查文件格式。</p>
          <img v-else-if="mode.id === 'image'" :key="source.url" :src="source.url" alt="原始图片"
               @error="originalError = true" />
          <video v-else :key="source.url" :src="source.url" aria-label="原始视频" controls
                 preload="metadata" playsinline @error="originalError = true" />
        </div>
      </section>

      <section class="panel">
        <header><h2>标注结果</h2><a v-if="task?.result_url" :href="`${task.result_url}?download=1`">下载结果</a></header>
        <div class="screen">
          <p v-if="!task?.result_url">{{ busy ? '正在生成标注结果' : '检测完成后在此预览' }}</p>
          <p v-else-if="resultError">无法在浏览器预览，可下载文件查看。</p>
          <img v-else-if="mode.id === 'image'" :src="task.result_url" alt="标注结果图片"
               @error="resultError = true" />
          <video v-else :src="task.result_url" aria-label="标注结果视频" controls preload="metadata"
                 playsinline @error="resultError = true" />
        </div>
        <div class="legend"><span class="boat">船只</span><span class="other">其他检出目标</span></div>
      </section>
    </div>
  </main>
</template>
