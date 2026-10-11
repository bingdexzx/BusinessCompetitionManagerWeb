<template>
  <router-view v-if="isPublic" />
  <AppLayout v-else>
    <MessageToastHost />
    <router-view />
  </AppLayout>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppLayout from '@/components/layout/AppLayout.vue'
import MessageToastHost from '@/components/MessageToastHost.vue'

const route = useRoute()
const isPublic = computed(() => Boolean(route.meta.public))
</script>
