<template>
  <div class="maps-manager">
    <!-- 顶部工具栏 -->
    <div class="mm-toolbar">
      <h2 class="mm-title">{{ canEdit ? "地图管理" : "地图" }}</h2>
      <div class="mm-actions">
        <el-button type="primary" @click="fitCanvas">适应画布</el-button>
        <el-button :loading="loading" @click="loadData">刷新数据</el-button>
        <el-button
          v-if="canEdit"
          :type="connectMode ? 'warning' : 'default'"
          @click="toggleConnect"
        >
          {{ connectMode ? "退出连线模式" : "连线模式" }}
        </el-button>
        <el-button v-if="canEdit" @click="openBgUrlDialog">导入背景</el-button>
        <el-button
          v-if="canEdit"
          type="danger"
          :disabled="!backgroundMeta"
          @click="clearBackground"
          >清除背景</el-button
        >
        <el-button
          v-if="canEdit && backgroundMeta"
          :type="bgEditMode ? 'success' : 'default'"
          @click="toggleBgEditMode"
          >{{ bgEditMode ? "完成背景编辑" : "背景编辑" }}</el-button
        >
      </div>
    </div>

    <!-- 背景图 URL 弹窗：新后端无背景上传接口，改为粘贴图片 URL（布局与画布能力保持不变） -->
    <el-dialog append-to-body v-model="bgUrlDialogVisible" title="导入背景" width="480px">
      <el-form label-width="80px">
        <el-form-item label="图片地址">
          <el-input
            v-model="bgUrlInput"
            placeholder="粘贴图片 URL（http(s):// 或 data:image/...）"
            clearable
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bgUrlDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploadingBg" @click="confirmBackgroundUrl">确定</el-button>
      </template>
    </el-dialog>

    <div v-if="!cid" class="no-comp-warning">
      请先在「比赛管理」中选择一个比赛
    </div>

    <!-- 主体三栏布局 -->
    <div class="mm-body">
      <!-- 左侧节点列表 -->
      <div v-if="canEdit" :class="['mm-left-panel', { 'is-open': leftOpen }]">
        <div class="panel-header">
          <span class="panel-title">节点列表</span>
          <el-button
            v-if="canEdit"
            size="small"
            type="primary"
            @click="openCreateDialog"
            >+ 新建</el-button
          >
        </div>
        <el-input
          v-model="nodeSearch"
          placeholder="搜索节点..."
          clearable
          size="default"
          class="panel-search"
        />
        <div class="node-list">
          <div
            v-for="node in filteredNodes"
            :key="node.id"
            class="node-item"
            :class="{ active: selectedNode?.id === node.id }"
            @click="focusNode(node)"
            @dblclick="jumpToNode(node)"
          >
            <span class="node-color-dot" :style="{ background: getNodeColor(node) }"></span>
            <span class="node-name">{{ node.name }}</span>
            <span class="node-region">{{ node.region }}</span>
          </div>
          <el-empty v-if="filteredNodes.length === 0 && !loading" description="暂无节点" />
        </div>
      </div>

      <!-- 中间 Konva 画布 -->
      <div ref="canvasWrapper" class="mm-canvas-wrapper">
        <v-stage
          ref="stageRef"
          :config="stageConfig"
          @mousedown="handleStageMouseDown"
          @mousemove="handleStageMouseMove"
          @mouseup="handleStageMouseUp"
          @dblclick="handleStageDblClick"
          @contextmenu="handleStageContextMenu"
          @wheel="handleStageWheel"
        >
          <!-- 背景图层：置于最底层，覆盖节点包围盒；非编辑态 listening=false 不拦截任何交互，
               编辑态开启 listening 并允许拖拽以调整位置 -->
          <v-layer :listening="bgEditMode">
            <v-image
              v-if="backgroundImage"
              :config="backgroundConfig"
              @dragend="handleBgDragEnd"
            />
          </v-layer>
          <!-- 边图层 -->
          <v-layer>
            <v-line
              v-for="edge in edges"
              :key="'e-' + edge.id"
              :config="getEdgeConfig(edge)"
              @click="selectEdge(edge)"
              @contextmenu="handleContextEdgeDelete($event, edge)"
            />
            <!-- 路径距离标签：仅在填写了距离值时显示，居中于边中点 -->
            <v-group
              v-for="edge in edgesWithDistance"
              :key="'el-' + edge.id"
              :config="getEdgeLabelGroupConfig(edge)"
              @click="selectEdge(edge)"
              @contextmenu="handleContextEdgeDelete($event, edge)"
            >
              <v-rect :config="getEdgeLabelBgConfig(edge)" />
              <v-text :config="getEdgeLabelTextConfig(edge)" />
            </v-group>
          </v-layer>
          <!-- 节点图层 -->
          <v-layer>
            <v-group
              v-for="node in nodes"
              :key="'g-' + node.id"
              :config="getNodeGroupConfig(node)"
              @dragstart="handleNodeDragStart(node)"
              @dragmove="handleNodeDragMove(node)"
              @dragend="handleNodeDragEnd(node)"
              @click="selectNode(node)"
              @dblclick="focusNode(node)"
              @contextmenu="handleContextNodeMenu($event, node)"
            >
              <v-circle :config="getNodeCircleConfig(node)" />
              <v-text :config="getNodeTextConfig(node)" />
            </v-group>
          </v-layer>
        </v-stage>

        <!-- 背景编辑面板：仅进入「背景编辑」模式且已有背景图时显示 -->
        <div v-if="bgEditMode && backgroundImage" class="bg-edit-panel">
          <div class="bg-edit-title">背景编辑</div>
          <div class="bg-edit-row">
            <span class="bg-edit-label">缩放</span>
            <el-slider
              v-model="bgScale"
              :min="0.1"
              :max="5"
              :step="0.01"
              :show-tooltip="true"
              :format-tooltip="(v: number) => Math.round(v * 100) + '%'"
              class="bg-edit-slider"
              @change="persistTransform"
            />
            <span class="bg-edit-val">{{ Math.round((bgTransform?.scale ?? 1) * 100) }}%</span>
          </div>
          <div class="bg-edit-row">
            <el-button size="small" @click="resetBgTransform">重置位置/缩放</el-button>
            <span class="bg-edit-hint">拖拽背景图可移动位置</span>
          </div>
        </div>

        <!-- 图例浮窗：无地图管理（data:map:edit）权限时显示，帮助只读查看者理解地图配色 -->
        <div v-if="!canEdit" class="mm-legend-panel" :class="{ collapsed: legendCollapsed }">
          <div class="legend-header" @click="legendCollapsed = !legendCollapsed">
            <span class="legend-title">图例</span>
            <span class="legend-caret">{{ legendCollapsed ? "展开" : "收起" }}</span>
          </div>
          <div v-show="!legendCollapsed" class="legend-body">
            <div class="legend-section">
              <div class="legend-section-title">节点类型</div>
              <div v-for="nt in nodeTypes" :key="nt.id" class="legend-item">
                <span class="legend-dot" :style="{ background: nt.color || '' }"></span>
                <span class="legend-name">{{ nt.name }}</span>
              </div>
              <div v-if="!nodeTypes.length" class="legend-empty">暂无节点类型</div>
            </div>
            <div class="legend-section">
              <div class="legend-section-title">路径类型</div>
              <div v-for="pt in pathTypes" :key="pt.id" class="legend-item">
                <span class="legend-line" :style="{ background: pt.color || '' }"></span>
                <span class="legend-name">{{ pt.name }}</span>
              </div>
              <div v-if="!pathTypes.length" class="legend-empty">暂无路径类型</div>
            </div>
          </div>
        </div>

        <!-- 手机模式：左右面板改为可滑出抽屉，避免遮挡地图；悬浮按钮开关 + 遮罩点击关闭 -->
        <template v-if="isPhone && canEdit">
          <div class="mm-drawer-mask" v-show="leftOpen || rightOpen" @click="closeDrawers"></div>
          <el-button class="mm-fab mm-fab-left" type="primary" size="small" @click="leftOpen = !leftOpen">节点</el-button>
          <el-button class="mm-fab mm-fab-right" type="primary" size="small" @click="rightOpen = !rightOpen">属性</el-button>
        </template>

      </div>

      <!-- 右侧属性面板 -->
      <div v-if="canEdit" :class="['mm-right-panel', { 'is-open': rightOpen }]">
        <!-- 节点属性-->
        <template v-if="selectedNode">
          <div class="panel-header">
            <span class="panel-title">节点属性</span>
            <el-tag :color="getNodeColor(selectedNode)" effect="dark" size="small">
              {{ getNodeTypeName(selectedNode.nodeTypeId) }}
            </el-tag>
          </div>
          <el-form label-width="60px" size="default" class="panel-form">
            <el-form-item label="名称">
              <el-input v-model="nodeForm.name" />
            </el-form-item>
            <el-form-item label="区域">
              <el-select
                v-model="nodeForm.region"
                filterable
                allow-create
                placeholder="选择或输入区域"
                style="width: 100%"
              >
                <el-option v-for="r in regions" :key="r" :label="r" :value="r" />
              </el-select>
            </el-form-item>
            <el-form-item label="类型">
              <el-select v-model="nodeForm.nodeTypeId" style="width: 100%">
                <el-option v-for="nt in nodeTypes" :key="nt.id" :label="nt.name" :value="nt.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="X坐标">
              <el-input-number v-model="nodeForm.x" :precision="2" style="width: 100%" />
            </el-form-item>
            <el-form-item label="Y坐标">
              <el-input-number v-model="nodeForm.y" :precision="2" style="width: 100%" />
            </el-form-item>
            <el-form-item>
              <el-button
                v-if="canEdit"
                type="primary"
                size="small"
                :loading="savingNode"
                @click="saveNode"
                >保存</el-button
              >
              <el-button
                v-if="canEdit"
                type="danger"
                size="small"
                @click="deleteNode"
                >删除</el-button
              >
            </el-form-item>
          </el-form>
        </template>

        <!-- 边属性-->
        <template v-else-if="selectedEdge">
          <div class="panel-header">
            <span class="panel-title">路径属性</span>
            <el-tag :color="getEdgeColor(selectedEdge)" effect="dark" size="small">
              {{ getPathTypeName(selectedEdge.pathTypeId) }}
            </el-tag>
          </div>
          <el-form label-width="60px" size="default" class="panel-form">
            <el-form-item label="起点">
              <span class="form-text">{{ getNodeName(selectedEdge.nodeAId) }}</span>
            </el-form-item>
            <el-form-item label="终点">
              <span class="form-text">{{ getNodeName(selectedEdge.nodeBId) }}</span>
            </el-form-item>
            <el-form-item label="距离">
              <el-input-number
                v-model="edgeForm.distance"
                :min="0"
                :precision="0"
                :controls="false"
                style="width: 100%"
              />
            </el-form-item>
            <el-form-item label="类型">
              <el-select v-model="edgeForm.pathTypeId" style="width: 100%">
                <el-option v-for="pt in pathTypes" :key="pt.id" :label="pt.name" :value="pt.id" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button
                v-if="canEdit"
                type="primary"
                size="small"
                :loading="savingEdge"
                @click="saveEdge"
                >保存</el-button
              >
              <el-button
                v-if="canEdit"
                type="danger"
                size="small"
                @click="deleteEdge"
                >删除</el-button
              >
            </el-form-item>
          </el-form>
        </template>

        <!-- 未选中 -->
        <div v-else class="panel-empty">
          <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
            <circle cx="24" cy="24" r="22" stroke="#C0C4CC" stroke-width="2" fill="none" />
            <text
              x="24"
              y="30"
              text-anchor="middle"
              fill="#C0C4CC"
              font-size="24"
              font-family="serif"
            >
              i
            </text>
          </svg>
          <p>点击节点或边查看属性</p>
          <p class="hint">双击空白区域新建节点</p>
        </div>
      </div>
    </div>

    <!-- 底部 Tab 管理 -->
    <div v-if="canEdit" class="mm-bottom">
      <el-tabs v-model="bottomTab" type="border-card">
        <!-- 节点类型管理 -->
        <el-tab-pane label="节点类型管理" name="nodeTypes">
          <div class="tab-toolbar">
            <el-button
              v-if="canEdit"
              type="primary"
              size="small"
              @click="openNodeTypeCreate"
              >+ 新建类型</el-button
            >
          </div>
          <el-table v-if="!isPhone" :data="nodeTypes" border stripe size="small" style="width: 100%">
            <el-table-column label="颜色" width="70">
              <template #default="{ row }">
                <span class="color-block" :style="{ background: row.color }"></span>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="名称" />
            <el-table-column prop="description" label="描述" />
            <el-table-column label="操作" width="240" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="showNodeTypeDetail(row)">详情</el-button>
                <el-button
                  v-if="canEdit"
                  size="small"
                  @click="openNodeTypeEdit(row)"
                  >编辑</el-button
                >
                <el-button
                  v-if="canEdit"
                  size="small"
                  type="danger"
                  @click="deleteNodeType(row)"
                  >删除</el-button
                >
              </template>
            </el-table-column>
          </el-table>
          <MobileCards
            v-else
            :data="nodeTypes"
            :columns="mapNodeTypeColumns"
            :row-key="(row: any) => row.id"
          >
            <template #color="{ row }">
              <span class="color-block" :style="{ background: row.color }"></span>
            </template>
            <template #actions="{ row }">
              <el-button size="small" @click="showNodeTypeDetail(row)">详情</el-button>
              <el-button
                v-if="canEdit"
                size="small"
                @click="openNodeTypeEdit(row)"
                >编辑</el-button
              >
              <el-button
                v-if="canEdit"
                size="small"
                type="danger"
                @click="deleteNodeType(row)"
                >删除</el-button
              >
            </template>
          </MobileCards>
        </el-tab-pane>

        <!-- 路径类型管理 -->
        <el-tab-pane label="路径类型管理" name="pathTypes">
          <div class="tab-toolbar">
            <el-button
              v-if="canEdit"
              type="primary"
              size="small"
              @click="openPathTypeCreate"
              >+ 新建类型</el-button
            >
          </div>
          <el-table v-if="!isPhone" :data="pathTypes" border stripe size="small" style="width: 100%">
            <el-table-column label="颜色" width="70">
              <template #default="{ row }">
                <span class="color-block" :style="{ background: row.color }"></span>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="名称" />
            <el-table-column prop="description" label="描述" />
            <el-table-column label="操作" width="240" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="showPathTypeDetail(row)">详情</el-button>
                <el-button
                  v-if="canEdit"
                  size="small"
                  @click="openPathTypeEdit(row)"
                  >编辑</el-button
                >
                <el-button
                  v-if="canEdit"
                  size="small"
                  type="danger"
                  @click="deletePathType(row)"
                  >删除</el-button
                >
              </template>
            </el-table-column>
          </el-table>
          <MobileCards
            v-else
            :data="pathTypes"
            :columns="mapPathTypeColumns"
            :row-key="(row: any) => row.id"
          >
            <template #color="{ row }">
              <span class="color-block" :style="{ background: row.color }"></span>
            </template>
            <template #actions="{ row }">
              <el-button size="small" @click="showPathTypeDetail(row)">详情</el-button>
              <el-button
                v-if="canEdit"
                size="small"
                @click="openPathTypeEdit(row)"
                >编辑</el-button
              >
              <el-button
                v-if="canEdit"
                size="small"
                type="danger"
                @click="deletePathType(row)"
                >删除</el-button
              >
            </template>
          </MobileCards>
        </el-tab-pane>

      </el-tabs>
    </div>

    <!-- 右键菜单 -->
    <Teleport to="body">
      <div
        v-if="contextMenu.visible"
        class="context-menu"
        :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
      >
        <template v-if="contextMenu.type === 'node'">
          <div class="menu-item" @click="contextNodeEdit">编辑节点</div>
          <div class="menu-item" @click="contextNodeDelete">删除节点</div>
          <div class="menu-item" @click="contextMenu.visible = false">取消</div>
        </template>
        <template v-else-if="contextMenu.type === 'stage'">
          <div class="menu-item" @click="openCreateAtContext">在此新建节点</div>
          <div class="menu-item" @click="contextMenu.visible = false">取消</div>
        </template>
      </div>
    </Teleport>

    <!-- 新建节点对话框 -->
    <el-dialog append-to-body
      v-model="createDialogVisible"
      title="新建节点"
      width="480px"
      @closed="resetCreateForm"
    >
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="createForm.name" placeholder="输入节点名称" />
        </el-form-item>
        <el-form-item label="区域" prop="region">
          <el-select
            v-model="createForm.region"
            filterable
            allow-create
            placeholder="选择或输入区域"
            style="width: 100%"
          >
            <el-option v-for="r in regions" :key="r" :label="r" :value="r" />
          </el-select>
        </el-form-item>
        <el-form-item label="类型" prop="nodeTypeId">
          <el-select v-model="createForm.nodeTypeId" placeholder="选择节点类型" style="width: 100%">
            <el-option v-for="nt in nodeTypes" :key="nt.id" :label="nt.name" :value="nt.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button
          v-if="canEdit"
          type="primary"
          :loading="creatingNode"
          @click="handleCreateNode"
          >确定</el-button
        >
      </template>
    </el-dialog>

    <!-- 节点类型编辑对话框 -->
    <el-dialog append-to-body
      v-model="nodeTypeDialogVisible"
      :title="nodeTypeIsEdit ? '编辑节点类型' : '新建节点类型'"
      width="480px"
      @closed="resetNodeTypeForm"
    >
      <el-form ref="nodeTypeFormRef" :model="nodeTypeForm" :rules="typeRules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="nodeTypeForm.name" placeholder="类型名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="nodeTypeForm.description" placeholder="类型描述" />
        </el-form-item>
        <el-form-item label="颜色">
          <div class="color-picker-row">
            <span
              v-for="c in presetColors"
              :key="c"
              class="color-chip"
              :class="{ active: nodeTypeForm.color === c }"
              :style="{ background: c }"
              @click="nodeTypeForm.color = c"
            ></span>
            <el-color-picker v-model="nodeTypeForm.color" size="small" />
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="nodeTypeDialogVisible = false">取消</el-button>
        <el-button
          v-if="canEdit"
          type="primary"
          :loading="saveNodeTypeLoading"
          @click="handleSaveNodeType"
          >确定</el-button
        >
      </template>
    </el-dialog>

    <!-- 路径类型编辑对话框 -->
    <el-dialog append-to-body
      v-model="pathTypeDialogVisible"
      :title="pathTypeIsEdit ? '编辑路径类型' : '新建路径类型'"
      width="480px"
      @closed="resetPathTypeForm"
    >
      <el-form ref="pathTypeFormRef" :model="pathTypeForm" :rules="typeRules" label-width="80px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="pathTypeForm.name" placeholder="类型名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="pathTypeForm.description" placeholder="类型描述" />
        </el-form-item>
        <el-form-item label="颜色">
          <div class="color-picker-row">
            <span
              v-for="c in presetColors"
              :key="c"
              class="color-chip"
              :class="{ active: pathTypeForm.color === c }"
              :style="{ background: c }"
              @click="pathTypeForm.color = c"
            ></span>
            <el-color-picker v-model="pathTypeForm.color" size="small" />
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="pathTypeDialogVisible = false">取消</el-button>
        <el-button
          v-if="canEdit"
          type="primary"
          :loading="savePathTypeLoading"
          @click="handleSavePathType"
          >确定</el-button
        >
      </template>
    </el-dialog>

    <!-- 节点类型详情对话框 -->
    <el-dialog append-to-body v-model="nodeTypeDetailVisible" title="节点类型详情" width="500px">
      <el-descriptions v-if="nodeTypeDetailData" :column="1" border>
        <el-descriptions-item label="名称">{{ nodeTypeDetailData.name }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{
          nodeTypeDetailData.description || "-"
        }}</el-descriptions-item>
        <el-descriptions-item label="颜色">
          <span class="color-block" :style="{ background: nodeTypeDetailData.color || '' }"></span>
          {{ nodeTypeDetailData.color }}
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{
          formatDateTime(nodeTypeDetailData.createdAt)
        }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{
          formatDateTime(nodeTypeDetailData.updatedAt)
        }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <!-- 路径类型详情对话框 -->
    <el-dialog append-to-body v-model="pathTypeDetailVisible" title="路径类型详情" width="500px">
      <el-descriptions v-if="pathTypeDetailData" :column="1" border>
        <el-descriptions-item label="名称">{{ pathTypeDetailData.name }}</el-descriptions-item>
        <el-descriptions-item label="描述">{{
          pathTypeDetailData.description || "-"
        }}</el-descriptions-item>
        <el-descriptions-item label="颜色">
          <span class="color-block" :style="{ background: pathTypeDetailData.color || '' }"></span>
          {{ pathTypeDetailData.color }}
        </el-descriptions-item>
        <el-descriptions-item label="创建时间">{{
          formatDateTime(pathTypeDetailData.createdAt)
        }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{
          formatDateTime(pathTypeDetailData.updatedAt)
        }}</el-descriptions-item>
      </el-descriptions>
    </el-dialog>

    <!-- 连线创建对话框 -->
    <el-dialog append-to-body v-model="edgeCreateDialogVisible" title="创建路径" width="400px">
      <el-form
        ref="edgeCreateFormRef"
        :model="edgeCreateForm"
        :rules="edgeCreateRules"
        label-width="80px"
      >
        <el-form-item label="路径类型" prop="pathTypeId">
          <el-select
            v-model="edgeCreateForm.pathTypeId"
            placeholder="选择路径类型"
            style="width: 100%"
          >
            <el-option v-for="pt in pathTypes" :key="pt.id" :label="pt.name" :value="pt.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="距离">
          <el-input-number
            v-model="edgeCreateForm.distance"
            :min="0"
            :precision="0"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="edgeCreateDialogVisible = false">取消</el-button>
        <el-button v-if="canEdit" type="primary" @click="confirmCreateEdge"
          >确定</el-button
        >
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick, watch } from "vue";
import { ElMessage, ElMessageBox } from "element-plus";
import { mapEdgeApi, mapNodeApi, mapNodeTypeApi, pathTypeApi } from "@/api/mapApi";
import type {
  MapEdgeRow as MapEdge,
  MapImpact,
  MapNodeRow as MapNode,
  MapNodeTypeRow as NodeType,
  PathTypeRow as PathType,
} from "@/api/mapTypes";
import { confirmDeleteWithImpact } from "@/utils/deleteConfirm";
import { useAuthStore } from "@/stores/auth";
import MobileCards from "@/components/common/MobileCards.vue";
import { errorMessage } from "@/utils/errors";
import { formatDateTime } from "@/utils/format";
import {
  Circle as VCircle,
  Group as VGroup,
  Image as VImage,
  Layer as VLayer,
  Line as VLine,
  Rect as VRect,
  Stage as VStage,
  Text as VText,
} from "vue-konva";

const NODE_RADIUS = 28;
// 枢纽页以路由 prop 传入当前比赛 id（useCompetitionStore().competitionId 的替代）
const props = defineProps<{ cid: string }>();
const authStore = useAuthStore();
// 手机断点（≤640px，与旧 useBreakpoint().isPhone 一致）；页面内联实现，不新增共享文件
const isPhone = ref(false);
let phoneMq: MediaQueryList | null = null;
function onPhoneChange() {
  isPhone.value = phoneMq?.matches ?? false;
}
// 写权限（对应旧 data:map:edit）：系统超管 或 本比赛 COMP_SUPER_ADMIN
const canEdit = computed(
  () =>
    authStore.isSuperuser ||
    authStore.memberships.some((m) => String(m.id) === props.cid && m.identity === "COMP_SUPER_ADMIN"),
);
// 图例浮窗（仅无管理权限时显示）的折叠状态
const legendCollapsed = ref(false);

// ===================== 数据 =====================
// 行类型来自 @/api/mapTypes（MapNode/MapEdge/MapNodeType/PathType 的 camelCase 字段）
const nodes = ref<MapNode[]>([]);
const edges = ref<MapEdge[]>([]);
const nodeTypes = ref<NodeType[]>([]);
const pathTypes = ref<PathType[]>([]);
// 区域候选：由节点 region 字段去重得到（区域实体/「区域总览」应用已裁剪，region 为节点上的自由字段）
const regions = computed<string[]>(() => {
  const set = new Set<string>();
  for (const n of nodes.value) {
    if (n.region) set.add(n.region);
  }
  return [...set];
});
const loading = ref(false);

const mapNodeTypeColumns = [
  { label: "颜色", slot: "color" },
  { prop: "name", label: "名称" },
  { prop: "description", label: "描述" },
];
const mapPathTypeColumns = [
  { label: "颜色", slot: "color" },
  { prop: "name", label: "名称" },
  { prop: "description", label: "描述" },
];

// ===================== 画布 =====================
const canvasWrapper = ref<HTMLElement>();
const stageRef = ref<any>(null);
const stageSize = ref({ width: 800, height: 500 });
const stageScale = ref(1);

const stageConfig = computed(() => ({
  width: stageSize.value.width,
  height: stageSize.value.height,
  scaleX: stageScale.value,
  scaleY: stageScale.value,
  draggable: false,
}));

let isPanning = false;
let lastPointer = { x: 0, y: 0 };
let stageOnMove = false;

// ===================== 连线模式 =====================
const connectMode = ref(false);
const connectFrom = ref<MapNode | null>(null);
let pendingFrom: MapNode | null = null;
let pendingTo: MapNode | null = null;
const edgeCreateDialogVisible = ref(false);
const edgeCreateForm = reactive({ pathTypeId: null as number | null, distance: 0 });
const edgeCreateFormRef = ref();
const edgeCreateRules = {
  pathTypeId: [{ required: true, message: "请选择路径类型", trigger: "change" }],
};

function toggleConnect() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  connectMode.value = !connectMode.value;
  connectFrom.value = null;
}

async function confirmCreateEdge() {
  if (!edgeCreateFormRef.value) return;
  const valid = await edgeCreateFormRef.value.validate().catch(() => false);
  if (!valid) return;
  if (!pendingFrom || !pendingTo) return;
  try {
    await mapEdgeApi.create(props.cid, {
      nodeAId: pendingFrom.id,
      nodeBId: pendingTo.id,
      distance: edgeCreateForm.distance,
      pathTypeId: edgeCreateForm.pathTypeId,
    });
    ElMessage.success("路径已创建");
    edgeCreateDialogVisible.value = false;
    await loadData();
  } catch (err) {
    ElMessage.error(errorMessage(err, "操作失败"));
  }
}

// ===================== 选中状态 =====================
const selectedNode = ref<MapNode | null>(null);
const selectedEdge = ref<MapEdge | null>(null);
const nodeSearch = ref("");
// 手机模式(≤640)：左右面板改为抽屉，用状态控制开合（仅手机生效，桌面/平板仍是三栏布局）
const leftOpen = ref(false);
const rightOpen = ref(false);
function closeDrawers() {
  leftOpen.value = false;
  rightOpen.value = false;
}

const filteredNodes = computed(() => {
  if (!nodeSearch.value) return nodes.value;
  const q = nodeSearch.value.toLowerCase();
  return nodes.value.filter(
    (n) => (n.name || "").toLowerCase().includes(q) || (n.region || "").toLowerCase().includes(q),
  );
});

// ===================== 节点属性表单 =====================
const nodeForm = reactive({ name: "", region: "", nodeTypeId: null as number | null, x: 0, y: 0 });
const savingNode = ref(false);

watch(selectedNode, (n) => {
  if (n) {
    nodeForm.name = n.name;
    nodeForm.region = n.region || "";
    nodeForm.nodeTypeId = n.nodeTypeId ?? null;
    nodeForm.x = n.x;
    nodeForm.y = n.y;
  }
});

// ===================== 边属性表单 =====================
const edgeForm = reactive({ distance: 0, pathTypeId: null as number | null });
const savingEdge = ref(false);

watch(selectedEdge, (e) => {
  if (e) {
    edgeForm.distance = e.distance ?? 0;
    edgeForm.pathTypeId = e.pathTypeId ?? null;
  }
});

// 手机模式：选中节点/边时自动展开右侧属性抽屉，便于查看/编辑（桌面/平板下右侧栏本就常驻，无影响）
watch([selectedNode, selectedEdge], ([n, e]) => {
  if (isPhone.value && (n || e)) rightOpen.value = true;
});

// ===================== 新建节点对话框 =====================
const createDialogVisible = ref(false);
const creatingNode = ref(false);
const pendingCreatePos = ref({ x: 200, y: 200 });
const createFormRef = ref();
const createForm = reactive({ name: "", region: "", nodeTypeId: null as number | null });
const createRules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
  region: [{ required: true, message: "请选择区域", trigger: "blur" }],
  nodeTypeId: [{ required: true, message: "请选择类型", trigger: "change" }],
};

// ===================== 右键菜单 =====================
const contextMenu = reactive({
  visible: false,
  x: 0,
  y: 0,
  type: "" as "node" | "stage" | "",
  data: null as any,
});

// ===================== 底部 Tab =====================
const bottomTab = ref("nodeTypes");

// ===================== 节点类型对话框 =====================
const nodeTypeDialogVisible = ref(false);
const nodeTypeIsEdit = ref(false);
const nodeTypeEditingId = ref<number | null>(null);
const saveNodeTypeLoading = ref(false);
const nodeTypeFormRef = ref();
const nodeTypeForm = reactive({ name: "", description: "", color: "#409EFF" });
const typeRules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
};

// ===================== 路径类型对话框 =====================
const pathTypeDialogVisible = ref(false);
const pathTypeIsEdit = ref(false);
const pathTypeEditingId = ref<number | null>(null);
const savePathTypeLoading = ref(false);
const pathTypeFormRef = ref();
const pathTypeForm = reactive({ name: "", description: "", color: "#67C23A" });

const nodeTypeDetailVisible = ref(false);
const nodeTypeDetailData = ref<NodeType | null>(null);
const pathTypeDetailVisible = ref(false);
const pathTypeDetailData = ref<PathType | null>(null);

const presetColors = ["#F56C6C", "#409EFF", "#67C23A", "#E6A23C", "#9C27B0", "#909399"];

// ===================== 工具函数 =====================
function getNodeById(id: number): MapNode | undefined {
  return nodes.value.find((n) => n.id === id);
}

function getNodeName(id: number): string {
  const n = getNodeById(id);
  return n ? n.name : `#${id}`;
}

function getNodeType(id: number | null | undefined): NodeType | undefined {
  return nodeTypes.value.find((nt) => nt.id === id);
}

function getNodeColor(node: MapNode): string {
  const nt = getNodeType(node.nodeTypeId);
  return nt?.color || "#A0A0A0";
}

function getNodeTypeName(id: number | null | undefined): string {
  const nt = getNodeType(id);
  return nt?.name || "未分类";
}

function getPathType(id: number | null | undefined): PathType | undefined {
  return pathTypes.value.find((pt) => pt.id === id);
}

function getEdgeColor(edge: MapEdge): string {
  const pt = getPathType(edge.pathTypeId);
  return pt?.color || "#A0A0A0";
}

function getPathTypeName(id: number | null | undefined): string {
  const pt = getPathType(id);
  return pt?.name || "未分类";
}

function getNodeGroupConfig(node: MapNode) {
  return {
    id: `node-${node.id}`,
    x: node.x,
    y: node.y,
    draggable: canEdit.value,
  };
}

function getNodeCircleConfig(node: MapNode) {
  return {
    x: 0,
    y: 0,
    radius: NODE_RADIUS,
    fill: getNodeColor(node),
    stroke: selectedNode.value?.id === node.id ? "#1D2129" : "#fff",
    strokeWidth: selectedNode.value?.id === node.id ? 3 : 2,
    shadowColor: "rgba(0,0,0,0.15)",
    shadowBlur: 6,
    shadowOffsetY: 2,
    hitStrokeWidth: 10,
  };
}

function getNodeTextConfig(node: MapNode) {
  return {
    x: 0,
    y: NODE_RADIUS + 14,
    text: node.name,
    fontSize: 12,
    fontFamily: '"PingFang SC", "Microsoft YaHei", sans-serif',
    fill: selectedNode.value?.id === node.id ? "#1D2129" : "#4E5969",
    align: "center",
    width: NODE_RADIUS * 4,
    offsetX: NODE_RADIUS * 2,
    offsetY: 0,
    listening: true,
  };
}

function getEdgeConfig(edge: MapEdge) {
  const from = getNodeById(edge.nodeAId);
  const to = getNodeById(edge.nodeBId);
  const points = from && to ? [from.x, from.y, to.x, to.y] : [0, 0, 0, 0];
  const isSelected = selectedEdge.value?.id === edge.id;
  return {
    id: `edge-${edge.id}`,
    points,
    stroke: getEdgeColor(edge),
    strokeWidth: isSelected ? 4 : 2,
    lineCap: "round",
    hitStrokeWidth: 12,
    name: `edge-${edge.id}`,
  };
}

// 仅在有距离值的边上显示距离标签，避免未填写的 0 距离污染画布
const edgesWithDistance = computed(() =>
  edges.value.filter((e) => typeof e.distance === "number" && e.distance > 0),
);

// 距离标签整体定位在边的中点（节点拖拽时随 from/to 坐标实时移动）
function getEdgeLabelGroupConfig(edge: MapEdge) {
  const from = getNodeById(edge.nodeAId);
  const to = getNodeById(edge.nodeBId);
  if (!from || !to) return { x: 0, y: 0 };
  return {
    x: (from.x + to.x) / 2,
    y: (from.y + to.y) / 2,
  };
}

// 距离文字为数字，按位数估算标签宽度（字号 11 时每位约 7px）
function getEdgeLabelWidth(edge: MapEdge): number {
  const text = String(edge.distance);
  return Math.max(22, text.length * 7 + 10);
}

function getEdgeLabelBgConfig(edge: MapEdge) {
  const w = getEdgeLabelWidth(edge);
  const isSelected = selectedEdge.value?.id === edge.id;
  return {
    x: 0,
    y: 0,
    width: w,
    height: 16,
    offsetX: w / 2,
    offsetY: 8,
    fill: isSelected ? "rgba(255,247,230,0.95)" : "rgba(255,255,255,0.9)",
    cornerRadius: 3,
    stroke: isSelected ? "#FF7D00" : "#E5E6EB",
    strokeWidth: 1,
    listening: true,
  };
}

function getEdgeLabelTextConfig(edge: MapEdge) {
  const w = getEdgeLabelWidth(edge);
  const isSelected = selectedEdge.value?.id === edge.id;
  return {
    x: 0,
    y: 0,
    width: w,
    height: 16,
    offsetX: w / 2,
    offsetY: 8,
    text: String(edge.distance),
    fontSize: 11,
    fontFamily: '"PingFang SC", "Microsoft YaHei", sans-serif',
    fill: isSelected ? "#1D2129" : "#4E5969",
    align: "center",
    verticalAlign: "middle",
    listening: false,
  };
}

// ===================== 删除影响确认 =====================
/**
 * 删除前影响确认：拉取 impact 接口（{removable, refs:[{kind,label,count}]}），
 * 将 refs 转成 confirmDeleteWithImpact 的级联子数据形态；
 * - removable === false（存在阻断性引用）→ 提示并中止删除；
 * - 用户取消确认 → 返回 false；impact 拉取失败不阻塞删除，按普通删除确认处理。
 */
async function confirmWithImpact(
  fetchImpact: () => Promise<MapImpact>,
  name: string,
  baseMessage?: string,
): Promise<boolean> {
  let impact: MapImpact | null = null;
  try {
    impact = await fetchImpact();
  } catch {
    impact = null;
  }
  if (impact && impact.removable === false) {
    const refs = (impact.refs || []).filter((r) => (r.count || 0) > 0);
    const detail = refs.length
      ? `（被 ${refs.map((r) => `${r.label} ${r.count} 条`).join("、")} 引用）`
      : "";
    ElMessage.error(`「${name}」正在被引用，无法删除${detail}`);
    return false;
  }
  try {
    await confirmDeleteWithImpact(
      name,
      { children: (impact?.refs || []).map((r) => ({ label: r.label, count: r.count })) },
      { baseMessage },
    );
    return true;
  } catch {
    return false; // 用户取消
  }
}

// ===================== 数据加载 =====================
async function loadData() {
  loading.value = true;
  try {
    if (!props.cid) {
      nodes.value = [];
      edges.value = [];
      nodeTypes.value = [];
      pathTypes.value = [];
      return;
    }
    // 四张地图表一次性拉取（地图数据量小，取全量渲染画布）
    const [typeRes, pathRes, nodeRes, edgeRes] = await Promise.all([
      mapNodeTypeApi.list(props.cid, { pageSize: 500 }),
      pathTypeApi.list(props.cid, { pageSize: 500 }),
      mapNodeApi.list(props.cid, { pageSize: 1000 }),
      mapEdgeApi.list(props.cid, { pageSize: 2000 }),
    ]);
    nodeTypes.value = typeRes.items || [];
    pathTypes.value = pathRes.items || [];
    nodes.value = nodeRes.items || [];
    edges.value = edgeRes.items || [];
    // 节点已确定：auto 模式立即锚定背景覆盖框（与背景图加载时机解耦，避免重新进入界面时背景错位）
    recomputeBBoxIfAuto();
  } catch (err) {
    ElMessage.error(errorMessage(err, "操作失败"));
  } finally {
    loading.value = false;
  }
}

// ===================== 画布事件 =====================
function getCanvasPos(_e: any) {
  const stage = stageRef.value?.getStage();
  if (!stage) return { x: 0, y: 0 };
  const pos = stage.getPointerPosition();
  return { x: pos?.x || 0, y: pos?.y || 0 };
}

function handleStageMouseDown(e: any) {
  // 点击空白区域开始平移
  if (e.target === e.target.getStage()) {
    isPanning = true;
    lastPointer = getCanvasPos(e);
  } else {
    isPanning = false;
  }
}

function handleStageMouseMove(e: any) {
  if (!isPanning) return;
  const pos = getCanvasPos(e);
  const dx = pos.x - lastPointer.x;
  const dy = pos.y - lastPointer.y;
  const stage = stageRef.value?.getStage();
  if (stage) {
    stage.x(stage.x() + dx);
    stage.y(stage.y() + dy);
    stage.batchDraw();
  }
  lastPointer = pos;
  stageOnMove = true;
}

function handleStageMouseUp() {
  isPanning = false;
  setTimeout(() => {
    stageOnMove = false;
  }, 50);
}

function handleStageDblClick(e: any) {
  // 双击空白区域新建节点（仅编辑权限）
  if (!canEdit.value) return;
  if (e.target !== e.target.getStage()) return;
  const pos = getCanvasPos(e);
  pendingCreatePos.value = { x: pos.x, y: pos.y };
  openCreateDialog();
}

function handleStageWheel(e: any) {
  e.evt.preventDefault();
  const scaleBy = 1.08;
  const stage = stageRef.value?.getStage();
  if (!stage) return;

  const oldScale = stage.scaleX();
  const pointer = stage.getPointerPosition();
  if (!pointer) return;

  const mousePointTo = {
    x: (pointer.x - stage.x()) / oldScale,
    y: (pointer.y - stage.y()) / oldScale,
  };

  const direction = e.evt.deltaY > 0 ? -1 : 1;
  const newScale = direction > 0 ? oldScale * scaleBy : oldScale / scaleBy;
  const clamped = Math.max(0.2, Math.min(5, newScale));

  stageScale.value = clamped;

  nextTick(() => {
    const s = stageRef.value?.getStage();
    if (!s) return;
    const newPos = {
      x: pointer.x - mousePointTo.x * clamped,
      y: pointer.y - mousePointTo.y * clamped,
    };
    s.x(newPos.x);
    s.y(newPos.y);
    s.batchDraw();
  });
}

function handleStageContextMenu(e: any) {
  e.evt.preventDefault();
  // 查看权限不展示右键菜单
  if (!canEdit.value) return;
  const pos = { x: e.evt.clientX, y: e.evt.clientY };
  // 如果点在空白区域
  if (e.target === e.target.getStage()) {
    const canvasPos = getCanvasPos(e);
    contextMenu.visible = true;
    contextMenu.x = pos.x;
    contextMenu.y = pos.y;
    contextMenu.type = "stage";
    contextMenu.data = canvasPos;
  }
}

// ===================== 节点操作 =====================
function selectNode(node: MapNode) {
  if (stageOnMove) return;

  // 连线模式
  if (connectMode.value) {
    if (!connectFrom.value) {
      connectFrom.value = node;
      ElMessage.info(`已选择起点: ${node.name}，请点击终点`);
      return;
    }
    if (connectFrom.value.id === node.id) {
      ElMessage.warning("不能连接自身");
      return;
    }
    // 弹出连线编辑对话框
    pendingFrom = connectFrom.value;
    pendingTo = node;
    edgeCreateForm.pathTypeId = null;
    edgeCreateForm.distance = 0;
    edgeCreateDialogVisible.value = true;
    connectFrom.value = null;
    return;
  }

  selectedEdge.value = null;
  selectedNode.value = node;
}

function focusNode(node: MapNode) {
  selectNode(node);
  jumpToNode(node);
}

function jumpToNode(node: MapNode) {
  const stage = stageRef.value?.getStage();
  if (!stage) return;
  const s = stageSize.value;
  stage.x(s.width / 2 - node.x * stageScale.value);
  stage.y(s.height / 2 - node.y * stageScale.value);
  stage.batchDraw();
}

function handleNodeDragStart(node: MapNode) {
  selectNode(node);
}

// 拖拽过程中实时同步位置：避免 Vue 响应式重渲染把节点拉回原位，
// 同时让相连的地图边实时跟随移动。
function handleNodeDragMove(node: MapNode) {
  const grp = stageRef.value?.getStage()?.findOne(`#node-${node.id}`);
  if (!grp) return;
  node.x = grp.x();
  node.y = grp.y();
}

async function handleNodeDragEnd(node: MapNode) {
  const grp = stageRef.value?.getStage()?.findOne(`#node-${node.id}`);
  if (!grp) return;
  const x = grp.x();
  const y = grp.y();
  try {
    await mapNodeApi.update(props.cid, node.id, {
      x: Math.round(x),
      y: Math.round(y),
    });
    node.x = x;
    node.y = y;
  } catch (err) {
    // revert
    grp.x(node.x);
    grp.y(node.y);
    ElMessage.error(errorMessage(err, "操作失败"));
  }
}

function handleContextNodeMenu(e: any, node: MapNode) {
  e.evt.preventDefault();
  // 查看权限不展示右键菜单
  if (!canEdit.value) return;
  selectNode(node);
  contextMenu.visible = true;
  contextMenu.x = e.evt.clientX;
  contextMenu.y = e.evt.clientY;
  contextMenu.type = "node";
  contextMenu.data = node;
}

function contextNodeEdit() {
  contextMenu.visible = false;
  // 已选中，无需额外操作
}

function contextNodeDelete() {
  contextMenu.visible = false;
  deleteNode();
}

async function deleteNode() {
  const node = selectedNode.value;
  if (!node) return;
  const ok = await confirmWithImpact(
    () => mapNodeApi.impact(props.cid, node.id),
    node.name ?? `#${node.id}`,
  );
  if (!ok) return;
  try {
    await mapNodeApi.remove(props.cid, node.id);
    ElMessage.success("节点已删除");
    selectedNode.value = null;
    loadData();
  } catch (err) {
    ElMessage.error(errorMessage(err, "操作失败"));
  }
}

async function saveNode() {
  const node = selectedNode.value;
  if (!node) return;
  savingNode.value = true;
  try {
    await mapNodeApi.update(props.cid, node.id, {
      name: nodeForm.name,
      region: nodeForm.region,
      nodeTypeId: nodeForm.nodeTypeId,
      x: nodeForm.x,
      y: nodeForm.y,
    });
    ElMessage.success("节点已更新");
    loadData();
  } catch (err) {
    ElMessage.error(errorMessage(err, "操作失败"));
  } finally {
    savingNode.value = false;
  }
}

// ===================== 边操作 =====================
function selectEdge(edge: MapEdge) {
  if (stageOnMove) return;
  selectedNode.value = null;
  selectedEdge.value = edge;
}

function handleContextEdgeDelete(e: any, edge: MapEdge) {
  e.evt.preventDefault();
  selectEdge(edge);
  deleteEdge();
}

async function deleteEdge() {
  const edge = selectedEdge.value;
  if (!edge) return;
  const ok = await confirmWithImpact(
    () => mapEdgeApi.impact(props.cid, edge.id),
    `路径#${edge.id}`,
  );
  if (!ok) return;
  try {
    await mapEdgeApi.remove(props.cid, edge.id);
    ElMessage.success("路径已删除");
    selectedEdge.value = null;
    loadData();
  } catch (err) {
    ElMessage.error(errorMessage(err, "操作失败"));
  }
}

async function saveEdge() {
  const edge = selectedEdge.value;
  if (!edge) return;
  savingEdge.value = true;
  try {
    await mapEdgeApi.update(props.cid, edge.id, {
      distance: edgeForm.distance,
      pathTypeId: edgeForm.pathTypeId,
    });
    ElMessage.success("路径已更新");
    loadData();
  } catch (err) {
    ElMessage.error(errorMessage(err, "操作失败"));
  } finally {
    savingEdge.value = false;
  }
}

// ===================== 新建节点 =====================
function openCreateDialog() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  createDialogVisible.value = true;
}

function openCreateAtContext() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  contextMenu.visible = false;
  pendingCreatePos.value = {
    x: contextMenu.data?.x || 200,
    y: contextMenu.data?.y || 200,
  };
  createDialogVisible.value = true;
}

function resetCreateForm() {
  createForm.name = "";
  createForm.region = "";
  createForm.nodeTypeId = null;
}

async function handleCreateNode() {
  if (!createFormRef.value) return;
  await createFormRef.value.validate(async (valid: boolean) => {
    if (!valid) return;
    creatingNode.value = true;
    try {
      await mapNodeApi.create(props.cid, {
        name: createForm.name,
        region: createForm.region || "",
        nodeTypeId: createForm.nodeTypeId,
        x: pendingCreatePos.value.x,
        y: pendingCreatePos.value.y,
      });
      ElMessage.success("节点已创建");
      createDialogVisible.value = false;
      loadData();
    } catch (err) {
      ElMessage.error(errorMessage(err, "操作失败"));
    } finally {
      creatingNode.value = false;
    }
  });
}

// ===================== 画布适应 =====================
function fitCanvas() {
  const stage = stageRef.value?.getStage();
  if (!stage) return;
  stage.x(0);
  stage.y(0);
  stageScale.value = 1;

  // 自动调整到节点范围
  if (nodes.value.length > 0) {
    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;
    nodes.value.forEach((n) => {
      if (n.x < minX) minX = n.x;
      if (n.y < minY) minY = n.y;
      if (n.x > maxX) maxX = n.x;
      if (n.y > maxY) maxY = n.y;
    });
    const w = maxX - minX + NODE_RADIUS * 6;
    const h = maxY - minY + NODE_RADIUS * 6;
    if (w > 0 && h > 0) {
      const scaleX = stageSize.value.width / w;
      const scaleY = stageSize.value.height / h;
      const s = Math.min(scaleX, scaleY, 1.5);
      stageScale.value = s;
      nextTick(() => {
        const st = stageRef.value?.getStage();
        if (!st) return;
        st.x((stageSize.value.width - (minX + maxX) * s) / 2);
        st.y((stageSize.value.height - (minY + maxY) * s) / 2);
        st.batchDraw();
      });
    }
  }
}

// ===================== 节点类型 CRUD =====================
function openNodeTypeCreate() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  nodeTypeIsEdit.value = false;
  nodeTypeEditingId.value = null;
  nodeTypeForm.name = "";
  nodeTypeForm.description = "";
  nodeTypeForm.color = "#409EFF";
  nodeTypeDialogVisible.value = true;
}

function openNodeTypeEdit(row: NodeType) {
  nodeTypeIsEdit.value = true;
  nodeTypeEditingId.value = row.id;
  nodeTypeForm.name = row.name;
  nodeTypeForm.description = row.description || "";
  nodeTypeForm.color = row.color || "#409EFF";
  nodeTypeDialogVisible.value = true;
}

function resetNodeTypeForm() {
  nodeTypeFormRef.value?.resetFields();
}

async function handleSaveNodeType() {
  if (!nodeTypeFormRef.value) return;
  await nodeTypeFormRef.value.validate(async (valid: boolean) => {
    if (!valid) return;
    saveNodeTypeLoading.value = true;
    try {
      const body = {
        name: nodeTypeForm.name,
        description: nodeTypeForm.description,
        color: nodeTypeForm.color,
      };
      if (nodeTypeIsEdit.value && nodeTypeEditingId.value) {
        await mapNodeTypeApi.update(props.cid, nodeTypeEditingId.value, body);
      } else {
        await mapNodeTypeApi.create(props.cid, body);
      }
      ElMessage.success(nodeTypeIsEdit.value ? "节点类型已更新" : "节点类型已创建");
      nodeTypeDialogVisible.value = false;
      loadData();
    } catch (err) {
      ElMessage.error(errorMessage(err, "操作失败"));
    } finally {
      saveNodeTypeLoading.value = false;
    }
  });
}

async function deleteNodeType(row: NodeType) {
  const ok = await confirmWithImpact(
    () => mapNodeTypeApi.impact(props.cid, row.id),
    row.name,
    `确定删除节点类型"${row.name}"吗？该类型下的所有地图节点及其关联边将一并删除，且不可恢复。`,
  );
  if (!ok) return;
  try {
    await mapNodeTypeApi.remove(props.cid, row.id);
    ElMessage.success("节点类型已删除");
    loadData();
  } catch (err) {
    ElMessage.error(errorMessage(err, "操作失败"));
  }
}

// ===================== 路径类型 CRUD =====================
function openPathTypeCreate() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  pathTypeIsEdit.value = false;
  pathTypeEditingId.value = null;
  pathTypeForm.name = "";
  pathTypeForm.description = "";
  pathTypeForm.color = "#67C23A";
  pathTypeDialogVisible.value = true;
}

function openPathTypeEdit(row: PathType) {
  pathTypeIsEdit.value = true;
  pathTypeEditingId.value = row.id;
  pathTypeForm.name = row.name;
  pathTypeForm.description = row.description || "";
  pathTypeForm.color = row.color || "#67C23A";
  pathTypeDialogVisible.value = true;
}

function resetPathTypeForm() {
  pathTypeFormRef.value?.resetFields();
}

async function handleSavePathType() {
  if (!pathTypeFormRef.value) return;
  await pathTypeFormRef.value.validate(async (valid: boolean) => {
    if (!valid) return;
    savePathTypeLoading.value = true;
    try {
      const body = {
        name: pathTypeForm.name,
        description: pathTypeForm.description,
        color: pathTypeForm.color,
      };
      if (pathTypeIsEdit.value && pathTypeEditingId.value) {
        await pathTypeApi.update(props.cid, pathTypeEditingId.value, body);
      } else {
        await pathTypeApi.create(props.cid, body);
      }
      ElMessage.success(pathTypeIsEdit.value ? "路径类型已更新" : "路径类型已创建");
      pathTypeDialogVisible.value = false;
      loadData();
    } catch (err) {
      ElMessage.error(errorMessage(err, "操作失败"));
    } finally {
      savePathTypeLoading.value = false;
    }
  });
}

async function deletePathType(row: PathType) {
  const ok = await confirmWithImpact(
    () => pathTypeApi.impact(props.cid, row.id),
    row.name,
    `确定删除路径类型"${row.name}"吗？使用该类型的所有地图边及载具通行配置将一并删除，且不可恢复。`,
  );
  if (!ok) return;
  try {
    await pathTypeApi.remove(props.cid, row.id);
    ElMessage.success("路径类型已删除");
    loadData();
  } catch (err) {
    ElMessage.error(errorMessage(err, "操作失败"));
  }
}

function showNodeTypeDetail(row: NodeType) {
  nodeTypeDetailData.value = row;
  nodeTypeDetailVisible.value = true;
}

function showPathTypeDetail(row: PathType) {
  pathTypeDetailData.value = row;
  pathTypeDetailVisible.value = true;
}

// ===================== 全局关闭右键菜单 =====================
function closeContextMenu() {
  contextMenu.visible = false;
}

// ===================== 地图背景 =====================
// 新后端无背景图上传接口：改为「粘贴图片 URL」，URL 与变换（位置/缩放）持久化在本地
// localStorage（按比赛隔离）；画布上的背景显示/拖拽/缩放/背景编辑能力与旧页面一致。
interface BackgroundMeta {
  url: string;
  transform: { x: number; y: number; scale: number } | null;
}
const BG_STORAGE_PREFIX = "bcm.mapBackground.";
function bgStorageKey(): string {
  return BG_STORAGE_PREFIX + String(props.cid);
}
/** 读取本地保存的背景元信息（无则 null）。 */
function loadLocalBackground(): BackgroundMeta | null {
  try {
    const raw = localStorage.getItem(bgStorageKey());
    if (!raw) return null;
    const meta = JSON.parse(raw) as BackgroundMeta;
    return meta && typeof meta.url === "string" && meta.url ? meta : null;
  } catch {
    return null;
  }
}
/** 保存/清除本地背景元信息（本地存储不可用时静默降级，仅影响刷新后恢复）。 */
function saveLocalBackground(meta: BackgroundMeta | null) {
  try {
    if (meta) localStorage.setItem(bgStorageKey(), JSON.stringify(meta));
    else localStorage.removeItem(bgStorageKey());
  } catch {
    // ignore
  }
}
const backgroundMeta = ref<BackgroundMeta | null>(null);
const backgroundImage = ref<HTMLImageElement | null>(null);
// 背景覆盖框（节点包围盒 + 留白），在加载时冻结，避免节点拖拽时背景抖动。
const bgBBox = ref<{ x: number; y: number; w: number; h: number } | null>(null);
// 「导入背景」URL 弹窗与应用中状态（替代旧的文件上传）
const bgUrlDialogVisible = ref(false);
const bgUrlInput = ref("");
const uploadingBg = ref(false);
// 背景编辑模式：开启后可拖拽背景图移动位置、用滑块调整缩放；关闭则背景不可交互。
const bgEditMode = ref(false);
// 背景变换（世界坐标）：由服务端持久化；null 表示按节点包围盒自动适配。
const bgTransform = ref<{ x: number; y: number; scale: number } | null>(null);
const BG_PADDING = 160; // 背景超出节点包围盒的留白，避免边缘节点压在图边

/** 由当前节点集合计算背景覆盖框（包围盒 + 留白）；无节点时返回 null（回退为图片原始尺寸置于原点）。 */
function computeBBox(): { x: number; y: number; w: number; h: number } | null {
  if (!nodes.value.length) return null;
  let minX = Infinity,
    minY = Infinity,
    maxX = -Infinity,
    maxY = -Infinity;
  for (const n of nodes.value) {
    if (n.x < minX) minX = n.x;
    if (n.y < minY) minY = n.y;
    if (n.x > maxX) maxX = n.x;
    if (n.y > maxY) maxY = n.y;
  }
  return {
    x: minX - BG_PADDING,
    y: minY - BG_PADDING,
    w: maxX - minX + BG_PADDING * 2,
    h: maxY - minY + BG_PADDING * 2,
  };
}

/**
 * 自动适配模式下背景图的显示矩形（等比 cover 铺满节点包围盒，保持图片原始比例、不变形、居中）。
 * - 以图片原始像素尺寸为基准，按 cover 比例缩放使其覆盖节点包围盒，再居中放置。
 * - auto 模式不依赖用户变换，仅作「未对齐时的占位底图」。
 * 该函数被 backgroundConfig（auto 分支）与「进入编辑态 / 重置」初始化 transform 时复用，
 * 保证从 auto 无缝切换到手动编辑时图片尺寸不跳变。
 */
function getAutoRect(): { x: number; y: number; w: number; h: number } {
  const img = backgroundImage.value;
  const iw = img?.naturalWidth || 800;
  const ih = img?.naturalHeight || 600;
  const box = bgBBox.value || { x: 0, y: 0, w: iw, h: ih };
  const cover = Math.max(box.w / iw, box.h / ih);
  const dw = iw * cover;
  const dh = ih * cover;
  return {
    x: box.x + (box.w - dw) / 2,
    y: box.y + (box.h - dh) / 2,
    w: dw,
    h: dh,
  };
}

/**
 * 重新锚定背景覆盖框（仅 auto 模式）：
 * - 手动模式（bgTransform 已设置）：保持用户调整后的背景变换，不跟随节点。
 * - auto 模式：覆盖框始终等于「最新节点集合的包围盒 + 留白」，因此节点坐标变化
 *   （loadData 重拉 / map-nodes 实时事件 / 拖拽保存后重拉）时背景自动跟随，永不错位。
 * 覆盖框只依赖节点集合，不依赖背景图加载时机——这样「重新进入界面」（tab 切换导致组件
 * 卸载重挂载）时，节点一就绪即正确锚定，无需等待图片加载，避免背景相对节点偏移。
 * 节点拖拽只改元素属性、不替换数组（下方 watch deep:false 不触发），故拖拽过程不抖动。
 */
function recomputeBBoxIfAuto() {
  if (bgTransform.value) return; // 手动调整模式：保持用户设置
  if (!nodes.value.length) {
    bgBBox.value = null;
    return;
  }
  bgBBox.value = computeBBox();
}

// 节点集合被整体替换（loadData / map-nodes 实时事件）时重新锚定覆盖框。
// deep:false：拖拽节点只改元素属性、不替换数组，不会触发，故拖拽不抖动。
watch(
  nodes,
  () => {
    recomputeBBoxIfAuto();
  },
  { deep: false },
);

/** 应用背景元信息：预加载图片；meta 为空则清空。 */
function applyBackgroundMeta(meta: BackgroundMeta | null) {
  backgroundMeta.value = meta || null;
  if (!meta || !meta.url) {
    backgroundImage.value = null;
    bgBBox.value = null;
    bgTransform.value = null;
    bgEditMode.value = false;
    return;
  }
  // 同步已持久化的变换（无则回退自动适配）。
  bgTransform.value = meta.transform ? { ...meta.transform } : null;
  const img = new Image();
  // 不设置 crossOrigin：背景仅作显示纹理，无需像素读取；跨源显示仍正常，
  // 仅 stage.toDataURL 导出时会因 canvas 污染失败（非核心路径）。
  img.onload = () => {
    backgroundImage.value = img;
    // auto 模式：节点集合此刻已就绪（onMounted 先加载数据再加载背景），重新锚定覆盖框。
    // 节点未就绪（极少见：图片快于首拉）也不影响——loadData 成功时已锚定过一次。
    recomputeBBoxIfAuto();
  };
  img.onerror = () => {
    backgroundImage.value = null;
    bgBBox.value = null;
    ElMessage.error("背景图加载失败");
  };
  // 直接使用粘贴的图片 URL（无后端上传接口，不做 baseUrl 前缀拼接）
  img.src = meta.url;
}

/** 拉取当前比赛的地图背景（本地保存的 URL + 变换）。 */
function loadBackground() {
  if (!props.cid) {
    applyBackgroundMeta(null);
    return;
  }
  applyBackgroundMeta(loadLocalBackground());
}

/** 「导入背景」按钮：打开粘贴图片 URL 弹窗（替代旧的文件上传）。 */
function openBgUrlDialog() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛管理」中选择一个比赛");
    return;
  }
  if (!canEdit.value) {
    ElMessage.warning("无权限操作地图背景");
    return;
  }
  bgUrlInput.value = backgroundMeta.value?.url ?? "";
  bgUrlDialogVisible.value = true;
}

/** 确认粘贴的背景图 URL：保存并应用（位置/缩放回到自动适配，可在「背景编辑」中再调整）。 */
function confirmBackgroundUrl() {
  const url = bgUrlInput.value.trim();
  if (!url) {
    ElMessage.warning("请粘贴图片 URL");
    return;
  }
  if (!/^https?:\/\//i.test(url) && !url.startsWith("data:image/")) {
    ElMessage.warning("图片 URL 需以 http(s):// 或 data:image/ 开头");
    return;
  }
  uploadingBg.value = true;
  try {
    const meta: BackgroundMeta = { url, transform: null };
    saveLocalBackground(meta);
    applyBackgroundMeta(meta);
    ElMessage.success("地图背景已更新");
    bgUrlDialogVisible.value = false;
  } catch (err) {
    ElMessage.error(errorMessage(err, "操作失败"));
  } finally {
    uploadingBg.value = false;
  }
}

/** 清除地图背景图（二次确认）。 */
async function clearBackground() {
  if (!props.cid) return;
  try {
    await ElMessageBox.confirm("确定清除地图背景图吗？此操作不可恢复。", {
      type: "warning",
    });
  } catch {
    return;
  }
  saveLocalBackground(null);
  applyBackgroundMeta(null);
  ElMessage.success("已清除地图背景");
}

/** 背景图 Konva 配置：置于节点包围盒下方、可随画布平移缩放。
 *  - 非编辑态：listening=false 不拦截交互，按节点包围盒自动适配（transform 为空）。
 *  - 编辑态：listening/draggable 开启，应用 bgTransform 的位置与缩放，可拖拽调整。 */
const backgroundConfig = computed(() => {
  if (!backgroundImage.value) return undefined;
  const img = backgroundImage.value;
  const t = bgTransform.value;
  if (t) {
    // 手动对齐模式：以图片「原始像素尺寸 × scale」显示（保持原始宽高比，不被拉伸），
    // 位置 = 用户保存的世界坐标。尺寸只取决于图片本身与 scale，与节点集合无关，
    // 因此重新进入界面时背景图位置/大小完全复现，不再随节点包围盒变化而偏移。
    const scale = t.scale ?? 1;
    return {
      image: img,
      x: t.x,
      y: t.y,
      width: (img.naturalWidth || 1) * scale,
      height: (img.naturalHeight || 1) * scale,
      draggable: bgEditMode.value,
      listening: bgEditMode.value,
      opacity: 0.85,
    };
  }
  // 自动适配模式：等比 cover 铺满节点包围盒（保持图片原始比例，不变形），居中放置。
  const r = getAutoRect();
  return {
    image: img,
    x: r.x,
    y: r.y,
    width: r.w,
    height: r.h,
    draggable: bgEditMode.value,
    listening: bgEditMode.value,
    opacity: 0.85,
  };
});

/** 缩放滑块的双向绑定：读取/写入 bgTransform.scale（进入编辑态时 transform 必已初始化）。 */
const bgScale = computed({
  get: () => bgTransform.value?.scale ?? 1,
  set: (v: number) => {
    if (!bgTransform.value) {
      // 防御性初始化：以当前 auto 显示状态为基底，避免尺寸跳变。
      const r = getAutoRect();
      bgTransform.value = { x: r.x, y: r.y, scale: v };
    } else {
      bgTransform.value = { ...bgTransform.value, scale: v };
    }
  },
});

/** 进入/退出背景编辑模式。进入时若尚无变换，以当前自动适配位置初始化，便于拖拽/缩放。 */
function toggleBgEditMode() {
  if (!backgroundImage.value) return;
  const entering = !bgEditMode.value;
  if (entering && !bgTransform.value) {
    // 以当前 auto 显示状态初始化，保证进入编辑态时图片尺寸不跳变，用户在原位置上微调。
    const r = getAutoRect();
    const iw = backgroundImage.value?.naturalWidth || 800;
    const cover = r.w / iw;
    bgTransform.value = {
      x: r.x,
      y: r.y,
      scale: cover,
    };
  }
  bgEditMode.value = !bgEditMode.value;
}

/** 拖拽背景图结束时，把新的世界坐标写入变换并持久化。 */
function handleBgDragEnd(e: any) {
  const node = e?.target;
  if (!node) return;
  const x = node.x();
  const y = node.y();
  if (!bgTransform.value) {
    // 防御路径：以 cover 比例初始化（与进入编辑态/重置保持一致），避免图片突然缩到原始像素尺寸而错位。
    const r = getAutoRect();
    const iw = backgroundImage.value?.naturalWidth || 800;
    const cover = r.w / iw;
    bgTransform.value = { x, y, scale: cover };
  } else {
    bgTransform.value = { ...bgTransform.value, x, y };
  }
  persistTransform();
}

/** 重置为自动适配（位置=节点包围盒左上、缩放=1）。 */
function resetBgTransform() {
  // 重置为自动适配显示状态（等比 cover 铺满节点包围盒），而非固定 1 倍，避免尺寸跳变。
  const r = getAutoRect();
  const iw = backgroundImage.value?.naturalWidth || 800;
  const cover = r.w / iw;
  bgTransform.value = { x: r.x, y: r.y, scale: cover };
  persistTransform();
}

/** 持久化当前背景变换（本地保存；新后端无背景接口，实时回调已裁剪，操作后本地刷新即可）。 */
function persistTransform() {
  const t = bgTransform.value;
  const meta = backgroundMeta.value;
  if (!t || !meta || !props.cid) return;
  if (!canEdit.value) return;
  saveLocalBackground({ url: meta.url, transform: t });
}

// ===================== 初始化 =====================
let resizeObserver: ResizeObserver | null = null;

function updateStageSize() {
  if (canvasWrapper.value) {
    // 留一点余量避免滚动条
    stageSize.value = {
      width: canvasWrapper.value.clientWidth - 2,
      height: canvasWrapper.value.clientHeight - 2,
    };
  }
}

onMounted(async () => {
  await loadData();
  loadBackground();

  updateStageSize();
  // 手机模式默认折叠图例浮窗，避免遮挡只读视图下的地图区域
  if (isPhone.value) legendCollapsed.value = true;

  resizeObserver = new ResizeObserver(() => {
    updateStageSize();
  });
  if (canvasWrapper.value) {
    resizeObserver.observe(canvasWrapper.value);
  }

  document.addEventListener("click", closeContextMenu);

  // 手机断点监听（≤640px 抽屉模式）
  phoneMq = window.matchMedia("(max-width: 640px)");
  onPhoneChange();
  if (phoneMq.addEventListener) {
    phoneMq.addEventListener("change", onPhoneChange);
  } else {
    window.addEventListener("resize", onPhoneChange);
  }
});

// 切换比赛（路由 cid 变化）时先清空全部地图数据再重新拉取，避免停留在上一个比赛的旧数据。
watch(
  () => props.cid,
  async () => {
    nodes.value = [];
    edges.value = [];
    nodeTypes.value = [];
    pathTypes.value = [];
    backgroundMeta.value = null;
    backgroundImage.value = null;
    bgBBox.value = null;
    bgTransform.value = null;
    bgEditMode.value = false;
    await loadData();
    loadBackground();
  },
);

onBeforeUnmount(() => {
  resizeObserver?.disconnect();
  document.removeEventListener("click", closeContextMenu);
  if (phoneMq?.removeEventListener) {
    phoneMq.removeEventListener("change", onPhoneChange);
  } else {
    window.removeEventListener("resize", onPhoneChange);
  }
});
</script>

<style scoped>
.maps-manager {
  display: flex;
  flex-direction: column;
  /* 挂在数据管理枢纽内（顶部有数据域菜单条），高度按外壳扣除给足画布 */
  height: calc(100vh - 210px); /* 回退 */
  height: calc(100dvh - 210px);
  min-height: 480px;
  background: #f5f7fa;
}

/* 工具栏 */
.mm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 0 12px;
  flex-shrink: 0;
}
.mm-title {
  font-size: 20px;
  font-weight: 500;
  color: #1f1f1f;
  margin: 0;
}
.mm-actions {
  display: flex;
  gap: 8px;
}

/* 主体 */
.mm-body {
  flex: 1;
  display: flex;
  gap: 0;
  min-height: 0;
  overflow: hidden;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e4e7ed;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}

/* 左侧面板 */
.mm-left-panel {
  width: 240px;
  min-width: 200px;
  background: #2c3544;
  color: #e0e3e8;
  display: flex;
  flex-direction: column;
  border-radius: 8px 0 0 8px;
  overflow: hidden;
}
.mm-left-panel .panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}
.mm-left-panel .panel-title {
  font-size: 14px;
  font-weight: 600;
  color: #c8cdd5;
}
.panel-search {
  margin: 10px 12px;
}
.panel-search :deep(.el-input__wrapper) {
  background: rgba(255, 255, 255, 0.08);
  border: 1px solid rgba(255, 255, 255, 0.1);
  box-shadow: none;
}
.panel-search :deep(.el-input__inner) {
  color: #e0e3e8;
}
.panel-search :deep(.el-input__inner::placeholder) {
  color: rgba(255, 255, 255, 0.35);
}

.node-list {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}
.node-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  cursor: pointer;
  transition: background 0.15s;
  font-size: 13px;
  color: #c8cdd5;
}
.node-item:hover {
  background: rgba(255, 255, 255, 0.06);
}
.node-item.active {
  background: rgba(64, 158, 255, 0.15);
  color: #fff;
}
.node-color-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
  border: 1px solid rgba(255, 255, 255, 0.3);
}
.node-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.node-region {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.4);
  flex-shrink: 0;
}

/* 画布区域 */
.mm-canvas-wrapper {
  flex: 1;
  overflow: hidden;
  background: #f0f2f5;
  position: relative;
}

/* 背景编辑浮动面板 */
.bg-edit-panel {
  position: absolute;
  left: 16px;
  bottom: 16px;
  z-index: 20;
  width: 320px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  backdrop-filter: blur(2px);
}
.bg-edit-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
  margin-bottom: 10px;
}
.bg-edit-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}
.bg-edit-row:last-child {
  margin-bottom: 0;
}
.bg-edit-label {
  font-size: 13px;
  color: #606266;
  flex-shrink: 0;
}
.bg-edit-slider {
  flex: 1;
}
.bg-edit-val {
  font-size: 13px;
  color: #409eff;
  width: 44px;
  text-align: right;
  flex-shrink: 0;
}
.bg-edit-hint {
  font-size: 12px;
  color: #909399;
}

/* 图例浮窗（无地图管理权限时显示，悬浮在画布右上角） */
.mm-legend-panel {
  position: absolute;
  right: 16px;
  top: 16px;
  z-index: 20;
  width: 220px;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid #e4e7ed;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  backdrop-filter: blur(2px);
  overflow: hidden;
}
.legend-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  cursor: pointer;
  user-select: none;
  background: #fafafa;
  border-bottom: 1px solid #e4e7ed;
}
.legend-title {
  font-size: 14px;
  font-weight: 600;
  color: #303133;
}
.legend-caret {
  font-size: 12px;
  color: #909399;
}
.legend-body {
  padding: 10px 12px;
  max-height: 60vh;
  overflow-y: auto;
}
.legend-section {
  margin-bottom: 12px;
}
.legend-section:last-child {
  margin-bottom: 0;
}
.legend-section-title {
  font-size: 12px;
  font-weight: 600;
  color: #606266;
  margin-bottom: 8px;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.legend-item:last-child {
  margin-bottom: 0;
}
.legend-dot {
  width: 14px;
  height: 14px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.1);
}
.legend-line {
  width: 18px;
  height: 4px;
  border-radius: 2px;
  flex-shrink: 0;
}
.legend-name {
  font-size: 13px;
  color: #303133;
}
.legend-empty {
  font-size: 12px;
  color: #c0c4cc;
}

/* 右侧面板 */
.mm-right-panel {
  width: 280px;
  min-width: 260px;
  background: #fff;
  border-left: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
  border-radius: 0 8px 8px 0;
  overflow: hidden;
}
.mm-right-panel .panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px;
  border-bottom: 1px solid #e4e7ed;
}
.mm-right-panel .panel-title {
  font-size: 14px;
  font-weight: 600;
  color: #1f1f1f;
}
.panel-form {
  padding: 16px;
  overflow-y: auto;
  flex: 1;
}
.panel-form :deep(.el-form-item) {
  margin-bottom: 14px;
}
.panel-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #c0c4cc;
  gap: 8px;
}
.panel-empty p {
  margin: 0;
  font-size: 13px;
}
.panel-empty .hint {
  font-size: 12px;
  color: #d0d4dc;
}

.form-text {
  color: #606266;
  font-size: 13px;
}

/* 底部 */
.mm-bottom {
  flex-shrink: 0;
  margin-top: 12px;
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e4e7ed;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}
.mm-bottom :deep(.el-tabs--border-card) {
  border: none;
  box-shadow: none;
}
.mm-bottom :deep(.el-tabs--border-card > .el-tabs__header) {
  background: #f5f7fa;
  border-bottom: 1px solid #e4e7ed;
}
.tab-toolbar {
  padding: 10px 0;
  display: flex;
  gap: 8px;
}

/* 颜色选择 */
.color-picker-row {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.color-chip {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  cursor: pointer;
  border: 2px solid transparent;
  transition: all 0.15s;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.12);
}
.color-chip:hover {
  transform: scale(1.1);
  box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
}
.color-chip.active {
  border-color: #1d2129;
  transform: scale(1.12);
  box-shadow: 0 0 0 2px rgba(29, 33, 41, 0.2);
}

.color-block {
  display: inline-block;
  width: 20px;
  height: 20px;
  border-radius: 4px;
  border: 1px solid rgba(0, 0, 0, 0.08);
}

/* 右键菜单 */
.context-menu {
  position: fixed;
  z-index: 3000;
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  padding: 4px 0;
  min-width: 140px;
  border: 1px solid #e4e7ed;
}
.menu-item {
  padding: 8px 16px;
  font-size: 13px;
  cursor: pointer;
  color: #303133;
  transition: background 0.12s;
}
.menu-item:hover {
  background: #f0f2f5;
}

/* Empty */
.node-list :deep(.el-empty__description) {
  color: rgba(255, 255, 255, 0.35);
}
.no-comp-warning {
  text-align: center;
  padding: 12px;
  margin-bottom: 12px;
  background: var(--color-warning-soft);
  border: 1px solid rgba(var(--color-warning-soft-rgb), 0.3);
  border-radius: 6px;
  color: #b45309;
  font-size: 13px;
}

/* 手机模式(≤640)：左右信息面板改为可滑出抽屉，避免遮挡中央地图显示区域 */
@media (max-width: 640px) {
  .mm-body {
    position: relative;
  }
  .mm-left-panel,
  .mm-right-panel {
    position: absolute;
    top: 0;
    bottom: 0;
    z-index: 40;
    width: min(82vw, 320px);
    box-shadow: 0 4px 24px rgba(0, 0, 0, 0.28);
    transition: transform 0.25s ease;
  }
  .mm-left-panel {
    left: 0;
    transform: translateX(-100%);
    border-radius: 0 8px 8px 0;
  }
  .mm-right-panel {
    right: 0;
    transform: translateX(100%);
    border-radius: 8px 0 0 8px;
  }
  .mm-left-panel.is-open {
    transform: translateX(0);
  }
  .mm-right-panel.is-open {
    transform: translateX(0);
  }
  .mm-canvas-wrapper {
    min-width: 0;
  }
  /* 抽屉遮罩：点击空白关闭 */
  .mm-drawer-mask {
    position: absolute;
    inset: 0;
    z-index: 39;
    background: rgba(0, 0, 0, 0.25);
  }
  /* 悬浮开关按钮 */
  .mm-fab {
    position: absolute;
    top: 12px;
    z-index: 45;
  }
  .mm-fab-left {
    left: 12px;
  }
  .mm-fab-right {
    right: 12px;
  }
  /* 背景编辑面板与图例在窄屏避免超出视口 */
  .bg-edit-panel {
    width: auto;
    max-width: calc(100vw - 32px);
  }
  .mm-legend-panel {
    width: auto;
    max-width: calc(100vw - 32px);
  }
}
</style>
