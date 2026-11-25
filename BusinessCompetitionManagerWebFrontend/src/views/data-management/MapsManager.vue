<template>
  <div class="maps-manager page">
    <PageHeader :title="canEdit ? '地图管理' : '地图'">
      <template #actions>
      <div class="mm-actions">
        <el-button type="default" @click="fitCanvas">适应画布</el-button>
        <el-button :loading="loading" @click="loadData">刷新</el-button>
        <el-button
          v-if="canEdit"
          :type="connectMode ? 'warning' : 'default'"
          @click="toggleConnect"
        >
          {{ connectMode ? "退出连线模式" : "连线模式" }}
        </el-button>
        <el-button v-if="canEdit" @click="openBgUrlDialog">导入背景</el-button>
        <el-button v-if="canImport" type="default" plain @click="openMapImport">导入 QGIS 地图</el-button>
        <el-tag v-if="isGeo" size="small" type="primary" class="mm-mode-tag">经纬度模式</el-tag>
        <el-button
          v-if="canEdit"
          type="danger"
          :disabled="!backgroundMeta"
          @click="clearBackground"
          >清除背景</el-button
        >
        <el-button
          v-if="canEdit && backgroundMeta && !isGeo"
          :type="bgEditMode ? 'success' : 'default'"
          @click="toggleBgEditMode"
          >{{ bgEditMode ? "完成背景编辑" : "背景编辑" }}</el-button
        >
      </div>
      </template>
    </PageHeader>

    <!-- 背景统一走服务端接口：本地上传或图片 URL -->
    <el-dialog append-to-body v-model="bgUrlDialogVisible" title="导入背景" width="560px" @closed="resetBgDialog">
      <el-form label-width="96px">
        <el-form-item label="本地图片">
          <el-button :loading="uploadingBg" @click="pickBgFile">选择图片文件</el-button>
          <span v-if="bgFileName" class="bg-file-name">{{ bgFileName }}</span>
          <input
            ref="bgFileInput"
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            style="display: none"
            @change="onBgFileSelected"
          />
        </el-form-item>
        <el-form-item label="图片地址">
          <el-input
            v-model="bgUrlInput"
            placeholder="粘贴图片 URL（http(s):// 或 data:image/...）；与本地图片二选一"
            clearable
            :disabled="!!bgFile"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="bgUrlDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="uploadingBg" @click="confirmBackground">确定</el-button>
      </template>
    </el-dialog>

    <!-- QGIS 地图导入：点→节点、线→边、面→区域（经纬度模式） -->
    <el-dialog
      append-to-body
      v-model="mapImportVisible"
      title="导入 QGIS 地图（.qgz）"
      width="560px"
    >
      <el-form label-width="96px" class="map-import-form">
        <el-form-item label="地图文件">
          <el-button :loading="importingMap" @click="pickMapFile">选择 .qgz 工程文件</el-button>
          <span v-if="importFileName" class="bg-file-name">{{ importFileName }}</span>
          <input
            ref="importFileInput"
            type="file"
            accept=".qgz"
            style="display: none"
            @change="onMapFileSelected"
          />
        </el-form-item>
        <el-form-item label="导入方式">
          <el-checkbox v-model="importReplace">先清空现有地图节点/边（整体重建）</el-checkbox>
        </el-form-item>
      </el-form>
      <div v-if="importReport" class="map-import-report">
        <div class="map-import-report__title">导入结果</div>
        <div class="map-import-report__grid">
          <span>新增节点 <b class="value-num">{{ importReport.nodesCreated }}</b></span>
          <span>复用节点 <b class="value-num">{{ importReport.nodesReused }}</b></span>
          <span>新增边 <b class="value-num">{{ importReport.edgesCreated }}</b></span>
          <span>跳过边 <b class="value-num">{{ importReport.edgesSkipped }}</b></span>
          <span>区域 <b class="value-num">{{ importReport.regions }}</b></span>
          <span
            >新增类型
            <b class="value-num">{{
              importReport.nodeTypesCreated + importReport.pathTypesCreated
            }}</b></span
          >
        </div>
        <div class="map-import-report__bounds">
          经纬度范围：{{ importReport.bounds.map((v: number) => v.toFixed(4)).join("，") }}
        </div>
        <el-alert
          v-if="importReport.missingLayers?.length"
          type="warning"
          :closable="false"
          show-icon
          class="map-import-missing"
          :title="`缺少数据源，未导入：${importReport.missingLayers.join('、')}`"
        />
      </div>
      <template #footer>
        <el-button @click="mapImportVisible = false">关闭</el-button>
        <el-button
          type="primary"
          :loading="importingMap"
          :disabled="!importFile"
          @click="confirmMapImport"
          >开始导入</el-button
        >
      </template>
    </el-dialog>

    <div v-if="!cid" class="no-comp-warning">
      请先在「比赛列表」中选择一个比赛
    </div>

    <div class="mm-body">
      <div v-if="canEdit" :class="['mm-left-panel', 'anim-fade-in-up', { 'is-open': leftOpen }]">
        <div class="panel-header">
          <span class="panel-title">节点列表</span>
          <el-button
            v-if="canEdit"
            size="small"
            type="primary"
            @click="openCreateDialog"
            >新建</el-button
          >
        </div>
        <el-input
          v-model="nodeSearch"
          placeholder="搜索节点…"
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
          <el-empty v-if="filteredNodes.length === 0 && !loading" description="暂无节点"  :image-size="72" />
        </div>
      </div>

      <div ref="canvasWrapper" class="mm-canvas-wrapper">
        <div v-if="pickedRegion" class="picked-region">
          已选区域：{{ pickedRegion }}
          <el-button link type="primary" size="small" @click="clearPickedRegion">清除</el-button>
        </div>
        <div v-if="navMode" class="nav-panel">
          <div class="nav-head">
            <span class="nav-title">路线导航</span>
            <el-button v-if="!navigationOnly" link size="small" @click="toggleNav">关闭</el-button>
          </div>
          <p class="nav-hint">在地图上依次点击起点、终点节点</p>
          <div class="nav-endpoint">
            <span class="nav-dot nav-dot-start" />
            <span class="nav-label">起点</span>
            <span class="nav-name">{{ navStart?.name || "点击地图选择" }}</span>
          </div>
          <div class="nav-endpoint">
            <span class="nav-dot nav-dot-end" />
            <span class="nav-label">终点</span>
            <span class="nav-name">{{ navEnd?.name || "点击地图选择" }}</span>
          </div>
          <div class="nav-actions">
            <el-button size="small" :disabled="!navStart || !navEnd" @click="swapNav">交换</el-button>
            <el-button size="small" :disabled="!navStart && !navEnd" @click="clearNav">清除</el-button>
          </div>
          <el-form label-width="96px" size="small" class="nav-form">
            <el-form-item label="最优">
              <el-select v-model="navWeight" style="width: 100%" @change="computeRoute">
                <el-option label="最短距离" value="distance" />
                <el-option label="最少节点" value="nodes" />
              </el-select>
            </el-form-item>
            <el-form-item label="交通">
              <el-checkbox-group v-model="navTypeIds" class="nav-types" @change="computeRoute">
                <el-checkbox v-for="pt in pathTypes" :key="pt.id" :value="pt.id">
                  {{ pt.name }}
                </el-checkbox>
              </el-checkbox-group>
            </el-form-item>
          </el-form>
          <el-alert v-if="navError" type="error" :closable="false" :title="navError" show-icon />
          <div v-if="navRoute" class="nav-result">
            <div class="nav-result-line">
              <b>{{ navRoute.distance.toFixed(2) }} km</b>
              <span>经过 {{ navRoute.nodes.length }} 个节点</span>
            </div>
            <div class="nav-steps">
              <span v-for="(node, index) in navRoute.nodes" :key="'step-' + node.id + '-' + index">
                {{ node.name }}<span v-if="index < navRoute.nodes.length - 1"> → </span>
              </span>
            </div>
            <div class="nav-segments">
              <span v-for="(edge, index) in navRoute.edges" :key="'seg-' + edge.id + '-' + index">
                {{
                  edge.id <= -300000
                    ? "陆路"
                    : edge.id < 0
                      ? "接驳"
                      : pathTypeName(edge.pathTypeId)
                }}
                {{ (edge.distance ?? 0).toFixed(2) }}km
                <span v-if="index < navRoute.edges.length - 1"> · </span>
              </span>
            </div>
            <div v-if="navRoute.edges.length" class="nav-summary">
              <div class="nav-summary-title">里程汇总</div>
              <div class="nav-summary-row">
                <span v-for="item in navModeSummary" :key="item.label">
                  {{ item.label }} <b>{{ item.distance.toFixed(2) }}km</b>
                </span>
              </div>
            </div>
            <div v-if="navRoute.edges.some((edge) => edge.id < 0)" class="nav-segments">
              灰色虚线为接入最近公路的接驳段（源地图没有直接连线），该段里程计入「公路」
            </div>
          </div>
        </div>
        <v-stage
          ref="stageRef"
          :config="stageConfig"
          @mousedown="handleStageMouseDown"
          @touchstart="handleStageTouchStart"
          @mousemove="handleStageMouseMove"
          @mouseup="handleStageMouseUp"
          @dblclick="handleStageDblClick"
          @contextmenu="handleStageContextMenu"
          @wheel="handleStageWheel"
          @click="handleStageClick"
          @tap="handleStageClick"
        >
          <!-- 背景层置底；非编辑态 listening=false，不拦截画布交互 -->
          <v-layer :listening="bgEditMode">
            <v-image
              v-if="backgroundImage"
              :config="backgroundConfig"
              @dragend="handleBgDragEnd"
            />
          </v-layer>
          <v-layer>
            <v-group v-for="layer in polygonLayers" :key="'layer-' + layer.name">
              <v-line
                v-for="(feature, featureIndex) in layer.features"
                :key="'poly-' + layer.name + '-' + featureIndex"
                :config="getPolygonConfig(feature, layer)"
                @click="pickRegion(feature)"
                @tap="pickRegion(feature)"
              />
              <v-text
                v-for="(feature, featureIndex) in layer.features"
                v-show="layer.role !== 'REGION' && !!feature.name"
                :key="'poly-label-' + layer.name + '-' + featureIndex"
                :config="getPolygonLabelConfig(feature, layer)"
              />
            </v-group>
          </v-layer>
          <v-layer>
            <v-line
              v-for="edge in visibleEdges"
              :key="'e-' + edge.id"
              :config="getEdgeConfig(edge)"
              @click="selectEdge(edge)"
            />
            <!-- 仅距离>0 的边显示标签，居中于边中点 -->
            <v-group
              v-for="edge in edgesWithDistance"
              :key="'el-' + edge.id"
              :config="getEdgeLabelGroupConfig(edge)"
              @click="selectEdge(edge)"
            >
              <v-rect :config="getEdgeLabelBgConfig(edge)" />
              <v-text :config="getEdgeLabelTextConfig(edge)" />
            </v-group>
          </v-layer>
          <v-layer v-if="navRoute">
            <v-line
              v-for="(edge, index) in navRoute.edges"
              :key="'route-' + edge.id + '-' + index"
              :config="getRouteLineConfig(edge)"
              :listening="false"
            />
          </v-layer>
          <v-layer>
            <v-group
              v-for="node in visibleNodes"
              :key="'g-' + node.id"
              :config="getNodeGroupConfig(node)"
              @dragstart="handleNodeDragStart(node)"
              @dragmove="handleNodeDragMove(node)"
              @dragend="handleNodeDragEnd(node)"
              @click="onNodeClick(node)"
              @tap="onNodeClick(node)"
              @dblclick="focusNode(node)"
            >
              <v-circle :config="getNodeCircleConfig(node)" />
              <v-text
                v-if="shouldShowNodeLabel(node)"
                :config="getNodeTextConfig(node)"
              />
            </v-group>
          </v-layer>
        </v-stage>

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

        <!-- 图例 / 图层开关：编辑者和只读用户都可按图层显示隐藏 -->
        <div class="mm-legend-panel" :class="{ collapsed: legendCollapsed }">
          <div class="legend-header" @click="legendCollapsed = !legendCollapsed">
            <span class="legend-title">图例</span>
            <span class="legend-caret">{{ legendCollapsed ? "展开" : "收起" }}</span>
          </div>
          <div v-show="!legendCollapsed" class="legend-body">
            <div class="legend-section">
              <div class="legend-section-title">节点类型</div>
              <div class="legend-item legend-toggle">
                <el-checkbox v-model="showNodeNames" size="small">显示节点名称</el-checkbox>
              </div>
              <div v-for="nt in nodeTypes" :key="nt.id" class="legend-item">
                <el-checkbox
                  :model-value="!hiddenNodeTypes.includes(nt.id)"
                  size="small"
                  @change="toggleNodeType(nt.id)"
                />
                <span class="legend-dot" :style="{ background: nt.color || '' }"></span>
                <span class="legend-name">{{ nt.name }}</span>
              </div>
              <div v-if="!nodeTypes.length" class="legend-empty">暂无节点类型</div>
            </div>
            <div class="legend-section">
              <div class="legend-section-title">路网接入</div>
              <div class="legend-item">
                <span class="legend-dot legend-dot-connected"></span>
                <span class="legend-name">已接入主路网</span>
              </div>
              <div class="legend-item">
                <span class="legend-dot legend-dot-isolated"></span>
                <span class="legend-name">
                  孤立体系 · 未接路网（{{ isolatedVisibleCount }}）
                </span>
              </div>
            </div>
            <div class="legend-section">
              <div class="legend-section-title">路径类型</div>
              <div v-for="pt in pathTypes" :key="pt.id" class="legend-item">
                <el-checkbox
                  :model-value="!hiddenPathTypes.includes(pt.id)"
                  size="small"
                  @change="togglePathType(pt.id)"
                />
                <span class="legend-line" :style="{ background: pt.color || '' }"></span>
                <span class="legend-name">{{ pt.name }}</span>
              </div>
              <div v-if="!pathTypes.length" class="legend-empty">暂无路径类型</div>
            </div>
            <div v-if="mapLayers.some((layer) => layer.kind === 'POLYGON' && layer.features.length)" class="legend-section">
              <div class="legend-section-title">面图层</div>
              <div
                v-for="layer in mapLayers.filter((item) => item.kind === 'POLYGON' && item.features.length)"
                :key="layer.name"
                class="legend-item"
              >
                <el-checkbox
                  :model-value="!hiddenLayers.includes(layer.name)"
                  size="small"
                  @change="toggleLayer(layer.name)"
                />
                <span class="legend-dot" :style="{ background: layer.color || '' }"></span>
                <span class="legend-name">{{ layer.name }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 手机端左右面板改为抽屉，避免遮挡地图 -->
        <template v-if="isPhone && canEdit">
          <div class="mm-drawer-mask" v-show="leftOpen || rightOpen" @click="closeDrawers"></div>
          <el-button class="mm-fab mm-fab-left" type="primary" size="small" @click="leftOpen = !leftOpen">节点</el-button>
          <el-button class="mm-fab mm-fab-right" type="primary" size="small" @click="rightOpen = !rightOpen">属性</el-button>
        </template>

      </div>

      <div v-if="canEdit" :class="['mm-right-panel', 'anim-fade-in-up', { 'is-open': rightOpen }]">
        <template v-if="selectedNode">
          <div class="panel-header">
            <span class="panel-title">节点属性</span>
            <el-tag :color="getNodeColor(selectedNode)" effect="dark" size="small">
              {{ getNodeTypeName(selectedNode.nodeTypeId) }}
            </el-tag>
          </div>
          <el-form label-width="96px" size="default" class="panel-form">
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
            <el-form-item :label="isGeo ? '经度' : 'X坐标'">
              <el-input-number v-model="nodeForm.x" :precision="isGeo ? 6 : 2" style="width: 100%" />
            </el-form-item>
            <el-form-item :label="isGeo ? '纬度' : 'Y坐标'">
              <el-input-number v-model="nodeForm.y" :precision="isGeo ? 6 : 2" style="width: 100%" />
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

        <template v-else-if="selectedEdge">
          <div class="panel-header">
            <span class="panel-title">路径属性</span>
            <el-tag :color="getEdgeColor(selectedEdge)" effect="dark" size="small">
              {{ getPathTypeName(selectedEdge.pathTypeId) }}
            </el-tag>
          </div>
          <el-form label-width="96px" size="default" class="panel-form">
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

    <div v-if="canEdit" class="mm-bottom anim-fade-in-up">
      <el-tabs v-model="bottomTab" type="border-card">
        <el-tab-pane label="节点类型管理" name="nodeTypes">
          <div class="tab-toolbar">
            <el-button
              v-if="canEdit"
              type="primary"
              size="small"
              @click="openNodeTypeCreate"
              >新建类型</el-button
            >
          </div>
          <el-table v-if="!isPhone" :data="nodeTypes" border stripe size="small" style="width: 100%">
            <el-table-column label="颜色" width="70">
              <template #default="{ row }">
                <span class="color-block" :style="{ background: row.color || '' }"></span>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="名称" />
            <el-table-column prop="description" label="描述" />
            <el-table-column label="操作" width="240" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="showNodeTypeDetail(row)" link type="primary">详情</el-button>
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
              <span class="color-block" :style="{ background: row.color || '' }"></span>
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

        <el-tab-pane label="路径类型管理" name="pathTypes">
          <div class="tab-toolbar">
            <el-button
              v-if="canEdit"
              type="primary"
              size="small"
              @click="openPathTypeCreate"
              >新建类型</el-button
            >
          </div>
          <el-table v-if="!isPhone" :data="pathTypes" border stripe size="small" style="width: 100%">
            <el-table-column label="颜色" width="70">
              <template #default="{ row }">
                <span class="color-block" :style="{ background: row.color || '' }"></span>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="名称" />
            <el-table-column prop="description" label="描述" />
            <el-table-column label="操作" width="240" fixed="right">
              <template #default="{ row }">
                <el-button size="small" @click="showPathTypeDetail(row)" link type="primary">详情</el-button>
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
              <span class="color-block" :style="{ background: row.color || '' }"></span>
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

        <!-- 区域在地图管理维护，区域总览页只做展示/配置 -->
        <el-tab-pane label="区域管理" name="regions">
          <div class="tab-toolbar">
            <el-button v-if="canEdit" type="primary" size="small" @click="openRegionCreate"
              >新建区域</el-button
            >
          </div>
          <el-table
            v-if="!isPhone"
            :data="regionsList"
            border
            stripe
            size="small"
            style="width: 100%"
          >
            <el-table-column prop="name" label="名称" />
            <el-table-column label="操作" width="100" fixed="right">
              <template #default="{ row }">
                <el-button v-if="canEdit" size="small" type="danger" @click="removeRegion(row.name)"
                  >删除</el-button
                >
              </template>
            </el-table-column>
          </el-table>
          <MobileCards
            v-else
            :data="regionsList"
            :columns="mapRegionColumns"
            :row-key="(row: any) => row.name"
          >
            <template #actions="{ row }">
              <el-button v-if="canEdit" size="small" type="danger" @click="removeRegion(row.name)"
                >删除</el-button
              >
            </template>
          </MobileCards>
        </el-tab-pane>

      </el-tabs>
    </div>

    <Teleport to="body">
      <div
        v-if="contextMenu.visible"
        class="context-menu"
        :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }"
      >
        <template v-if="contextMenu.type === 'stage'">
          <div class="menu-item" @click="openCreateAtContext">在此新建节点</div>
          <div class="menu-item" @click="contextMenu.visible = false">取消</div>
        </template>
      </div>
    </Teleport>

    <el-dialog append-to-body
      v-model="createDialogVisible"
      title="新建节点"
      width="560px"
      @closed="resetCreateForm"
    >
      <el-form ref="createFormRef" :model="createForm" :rules="createRules" label-width="96px">
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

    <el-dialog append-to-body
      v-model="nodeTypeDialogVisible"
      :title="nodeTypeIsEdit ? '编辑节点类型' : '新建节点类型'"
      width="560px"
      @closed="resetNodeTypeForm"
    >
      <el-form ref="nodeTypeFormRef" :model="nodeTypeForm" :rules="typeRules" label-width="96px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="nodeTypeForm.name" placeholder="请输入类型名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="nodeTypeForm.description" placeholder="请输入类型描述" />
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

    <el-dialog append-to-body
      v-model="pathTypeDialogVisible"
      :title="pathTypeIsEdit ? '编辑路径类型' : '新建路径类型'"
      width="560px"
      @closed="resetPathTypeForm"
    >
      <el-form ref="pathTypeFormRef" :model="pathTypeForm" :rules="typeRules" label-width="96px">
        <el-form-item label="名称" prop="name">
          <el-input v-model="pathTypeForm.name" placeholder="请输入类型名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="pathTypeForm.description" placeholder="请输入类型描述" />
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

    <el-drawer direction="rtl" append-to-body v-model="nodeTypeDetailVisible" title="节点类型详情" size="480px">
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
    </el-drawer>

    <el-drawer direction="rtl" append-to-body v-model="pathTypeDetailVisible" title="路径类型详情" size="480px">
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
    </el-drawer>

    <el-dialog
      append-to-body
      v-model="regionDialogVisible"
      title="新建区域"
      width="420px"
      @closed="newRegionName = ''"
    >
      <el-form
        ref="regionFormRef"
        :model="{ name: newRegionName }"
        :rules="regionRules"
        label-width="96px"
      >
        <el-form-item label="名称" prop="name">
          <el-input v-model="newRegionName" placeholder="输入区域名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="regionDialogVisible = false">取消</el-button>
        <el-button v-if="canEdit" type="primary" @click="addRegion">确定</el-button>
      </template>
    </el-dialog>

    <el-dialog append-to-body v-model="edgeCreateDialogVisible" title="创建路径" width="420px">
      <el-form
        ref="edgeCreateFormRef"
        :model="edgeCreateForm"
        :rules="edgeCreateRules"
        label-width="96px"
      >
        <el-form-item label="路径类型" prop="pathTypeId">
          <el-select
            v-model="edgeCreateForm.pathTypeId"
            placeholder="请选择路径类型"
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
/* eslint-disable @typescript-eslint/no-explicit-any -- 基础数据行/画布事件字段动态变化，逐字段建模收益低 */
import { ref, reactive, computed, onMounted, onBeforeUnmount, nextTick, watch } from "vue";
import PageHeader from '@/components/common/PageHeader.vue'
import { ElMessage, ElMessageBox } from "element-plus";
import { createRegion, deleteRegion, getRegionMapOverview } from "@/api";
import {
  getMapSettings,
  importQGISMap,
  mapEdgeApi,
  mapNodeApi,
  mapNodeTypeApi,
  pathTypeApi,
} from "@/api/mapApi";
import type { MapImportReport, MapMode } from "@/api/mapApi";
import type { MapLayerSetting } from "@/api/mapTypes";
import {
  deleteMapBackground,
  getMapBackground,
  saveMapBackground,
  updateMapBackgroundTransform,
} from "@/api/filesApi";
import type { MapBackground as BackgroundMeta } from "@/api/filesApi";
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
import { useResourceRefresh } from "@/composables/useNotifications";
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
const props = defineProps<{
  cid: string;
  // 工具箱里的「地图导航」页：导航面板常驻、不显示开关；普通地图页只展示地图
  navigationOnly?: boolean;
}>();
const authStore = useAuthStore();
// 手机断点 ≤640px，与旧 useBreakpoint().isPhone 对齐
const isPhone = ref(false);
let phoneMq: MediaQueryList | null = null;
function onPhoneChange() {
  isPhone.value = phoneMq?.matches ?? false;
}
// 写权限：系统超级管理员（比赛超级管理员身份已取消，2026-11）
const canImport = computed(() => authStore.isSuperuser);
// 地图数据完全由 QGIS 导入生成，页面不再提供手工增删改
const canEdit = computed(() => false);
const legendCollapsed = ref(false);

const nodes = ref<MapNode[]>([]);
const edges = ref<MapEdge[]>([]);
const nodeTypes = ref<NodeType[]>([]);
const pathTypes = ref<PathType[]>([]);
const mapLayers = ref<MapLayerSetting[]>([]);
const hiddenNodeTypes = ref<number[]>([]);
/** 没接上「主路网」的节点：孤立体系，图例与节点描边都会标出来 */
const isolatedNodes = ref<Set<number>>(new Set());
const hiddenPathTypes = ref<number[]>([]);
const hiddenLayers = ref<string[]>([]);
const pickedRegion = ref("");
const navMode = ref(props.navigationOnly === true);
const navStart = ref<MapNode | null>(null);
const navEnd = ref<MapNode | null>(null);
const navWeight = ref<"distance" | "nodes">("distance");
const navTypeIds = ref<number[]>([]);
const navTypesInitialized = ref(false);
const navError = ref("");
interface NavRoute {
  nodes: MapNode[];
  edges: MapEdge[];
  distance: number;
}
const navRoute = ref<NavRoute | null>(null);
// 区域候选 = 节点所属区域 ∪ 无节点区域实体（区域在地图页新建，节点只存名称）
const regions = ref<string[]>([]);
// 区域名 -> Region 实体 id；节点自定义区域为 null
const regionIdMap = ref<Map<string, number | null>>(new Map());
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
const mapRegionColumns = [{ prop: "name", label: "名称" }];

// 区域只在地图管理维护，区域总览页不再新建/重命名/删除
const regionDialogVisible = ref(false);
const newRegionName = ref("");
const regionFormRef = ref();
const regionRules = { name: [{ required: true, message: "请输入区域名称", trigger: "blur" }] };
const regionsList = computed(() =>
  regions.value.map((r) => ({ name: r, id: regionIdMap.value.get(r) ?? null })),
);

async function loadRegionsFromServer() {
  if (!props.cid) {
    regions.value = [];
    regionIdMap.value = new Map();
    return;
  }
  try {
    const list = (await getRegionMapOverview(props.cid)) || [];
    const map = new Map<string, number | null>();
    const names: string[] = [];
    for (const r of list) {
      if (!r.region) continue;
      if (!map.has(r.region)) {
        map.set(r.region, r.id ?? null);
        names.push(r.region);
      }
    }
    regions.value = names;
    regionIdMap.value = map;
  } catch (err) {
    ElMessage.error(errorMessage(err, "区域列表加载失败"));
  }
}

function openRegionCreate() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛列表」中选择一个比赛");
    return;
  }
  newRegionName.value = "";
  regionDialogVisible.value = true;
}

async function addRegion() {
  if (!regionFormRef.value) return;
  const valid = await regionFormRef.value.validate().catch(() => false);
  if (!valid) return;
  const name = newRegionName.value.trim();
  if (regions.value.includes(name)) {
    ElMessage.warning("区域名称已存在");
    return;
  }
  try {
    await createRegion(props.cid, { name, description: "" });
    computeIsolation();
    await loadRegionsFromServer();
    ElMessage.success("区域已新建");
    newRegionName.value = "";
    regionDialogVisible.value = false;
  } catch (err) {
    ElMessage.error(errorMessage(err, "新建区域失败"));
  }
}

async function removeRegion(name: string) {
  const id = regionIdMap.value.get(name);
  if (!id) {
    ElMessage.warning("该区域由地图节点定义，请在地图节点上移除其所属区域");
    return;
  }
  try {
    await ElMessageBox.confirm(`确定删除区域「${name}」？该操作不可恢复。`, "删除区域", {
      type: "warning",
      confirmButtonText: "删除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await deleteRegion(props.cid, id);
    computeIsolation();
    await loadRegionsFromServer();
    ElMessage.success("区域已删除");
  } catch (err) {
    ElMessage.error(errorMessage(err, "删除区域失败"));
  }
}

const canvasWrapper = ref<HTMLElement>();
const stageRef = ref<any>(null);
const stageSize = ref({ width: 800, height: 500 });
const stageScale = ref(1);

// ---------- 坐标模式：PIXEL=画布像素（手绘）/ GEO=经纬度（QGIS 导入） ----------
const mapMode = ref<MapMode>("PIXEL");
const mapBounds = ref<number[]>([]);
const dragPos = ref<Record<number, { x: number; y: number }>>({});

const geoView = computed(() => {
  if (mapMode.value !== "GEO") return null;
  const b = mapBounds.value;
  if (!b || b.length !== 4) return null;
  const [minLon, minLat, maxLon, maxLat] = b as [number, number, number, number];
  const lonSpan = maxLon - minLon;
  const latSpan = maxLat - minLat;
  if (!(lonSpan > 0) || !(latSpan > 0)) return null;
  const { width, height } = stageSize.value;
  const scale = Math.min(width / lonSpan, height / latSpan) * 0.92;
  const w = lonSpan * scale;
  const h = latSpan * scale;
  return { minLon, maxLat, scale, x: (width - w) / 2, y: (height - h) / 2, w, h };
});
const isGeo = computed(() => !!geoView.value);

/** 距离口径：只有「真的是经纬度」的地图才用球面距离。
 *  早期 QGIS 导入会把像素坐标系的项目也标成 GEO，照 isGeo 走会把里程放大近百倍。 */
const geoMetric = computed(() => {
  if (!isGeo.value) return false;
  const sample = nodes.value.slice(0, 200);
  return (
    sample.length > 0 &&
    sample.every((node) => Math.abs(node.x) <= 180 && Math.abs(node.y) <= 90)
  );
});

/** 节点画布渲染坐标：GEO 按经纬度投影（拖拽中优先用实时坐标，供相连的边跟随） */
function nodePos(node: MapNode): { x: number; y: number } {
  const live = dragPos.value[node.id];
  if (live) return live;
  const g = geoView.value;
  if (!g) return { x: node.x, y: node.y };
  return {
    x: g.x + (node.x - g.minLon) * g.scale,
    y: g.y + (g.maxLat - node.y) * g.scale,
  };
}

/** 画布坐标 → 存储坐标（GEO 模式反投影为经纬度，保留 6 位小数） */
function toStorage(x: number, y: number): { x: number; y: number } {
  const g = geoView.value;
  if (!g) return { x, y };
  return {
    x: Number((g.minLon + (x - g.x) / g.scale).toFixed(6)),
    y: Number((g.maxLat - (y - g.y) / g.scale).toFixed(6)),
  };
}

// ---------- QGIS 地图导入（.qgz 工程：点→节点、线→边、面→区域） ----------
const mapImportVisible = ref(false);
const importingMap = ref(false);
const importReplace = ref(false);
const importFile = ref<File | null>(null);
const importFileName = ref("");
const importReport = ref<MapImportReport | null>(null);
const importFileInput = ref<HTMLInputElement | null>(null);

function openMapImport() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛列表」中选择一个比赛");
    return;
  }
  importFile.value = null;
  importFileName.value = "";
  importReport.value = null;
  mapImportVisible.value = true;
}

function pickMapFile() {
  importFileInput.value?.click();
}

function onMapFileSelected(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0];
  if (file) {
    if (!file.name.toLowerCase().endsWith(".qgz")) {
      ElMessage.warning("请选择 QGIS 工程文件（.qgz）");
      input.value = "";
      return;
    }
    importFile.value = file;
    importFileName.value = file.name;
  }
  input.value = "";
}

async function confirmMapImport() {
  if (!importFile.value || !props.cid) return;
  importingMap.value = true;
  try {
    const report = await importQGISMap(props.cid, importFile.value, {
      replace: importReplace.value,
    });
    importReport.value = report;
    ElMessage.success(
      `导入完成：新增节点 ${report.nodesCreated}、边 ${report.edgesCreated}、区域 ${report.regions}`,
    );
    await loadData();
    recomputeBBoxIfAuto();
  } catch (err) {
    ElMessage.error(errorMessage(err, "导入失败"));
  } finally {
    importingMap.value = false;
  }
}

const stageConfig = computed(() => ({
  width: stageSize.value.width,
  height: stageSize.value.height,
  draggable: false,
}));

let isPanning = false;
// 这次按下之后是否真的拖动过：拖动结束后的 click 不应该再触发选中/选区域
let panMoved = false;
// 触屏双指缩放
let pinchActive = false;
let pinchStartDistance = 0;
let pinchContentX = 0;
let pinchContentY = 0;
let panStartX = 0;
let panStartY = 0;
let panDx = 0;
let panDy = 0;
let panOriginX = 0;
let panOriginY = 0;
let panContainer: HTMLElement | null = null;
let zoomPreviewActive = false;
let zoomBaseScale = 1;
let zoomBaseX = 0;
let zoomBaseY = 0;
let zoomCurrentScale = 1;
let zoomCurrentX = 0;
let zoomCurrentY = 0;
let zoomTimer: ReturnType<typeof setTimeout> | null = null;
let stageOnMove = false;

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
    ElMessage.warning("请先在「比赛列表」中选择一个比赛");
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

const selectedNode = ref<MapNode | null>(null);
const selectedEdge = ref<MapEdge | null>(null);
const nodeSearch = ref("");
const leftOpen = ref(false);
const rightOpen = ref(false);
function closeDrawers() {
  leftOpen.value = false;
  rightOpen.value = false;
}

const filteredNodes = computed(() => {
  let rows = visibleNodes.value;
  if (pickedRegion.value) {
    rows = rows.filter((node) => (node.region || "") === pickedRegion.value);
  }
  if (!nodeSearch.value) return rows;
  const q = nodeSearch.value.toLowerCase();
  return rows.filter(
    (n) => (n.name || "").toLowerCase().includes(q) || (n.region || "").toLowerCase().includes(q),
  );
});

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

const edgeForm = reactive({ distance: 0, pathTypeId: null as number | null });
const savingEdge = ref(false);

watch(selectedEdge, (e) => {
  if (e) {
    edgeForm.distance = e.distance ?? 0;
    edgeForm.pathTypeId = e.pathTypeId ?? null;
  }
});

watch([selectedNode, selectedEdge], ([n, e]) => {
  if (isPhone.value && (n || e)) rightOpen.value = true;
});

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

const contextMenu = reactive({
  visible: false,
  x: 0,
  y: 0,
  type: "" as "node" | "stage" | "",
  data: null as any,
});

const bottomTab = ref("nodeTypes");

const nodeTypeDialogVisible = ref(false);
const nodeTypeIsEdit = ref(false);
const nodeTypeEditingId = ref<number | null>(null);
const saveNodeTypeLoading = ref(false);
const nodeTypeFormRef = ref();
const nodeTypeForm = reactive({ name: "", description: "", color: "#409EFF" });
const typeRules = {
  name: [{ required: true, message: "请输入名称", trigger: "blur" }],
};

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
  const pos = nodePos(node);
  return {
    id: `node-${node.id}`,
    x: pos.x,
    y: pos.y,
    draggable: canEdit.value,
  };
}

function getNodeCircleConfig(node: MapNode) {
  const isStart = navStart.value?.id === node.id;
  const isEnd = navEnd.value?.id === node.id;
  const selected = selectedNode.value?.id === node.id;
  const isolated = isolatedNodes.value.has(node.id);
  const highlighted = isStart || isEnd || selected;
  return {
    x: 0,
    y: 0,
    radius: nodeRadius.value,
    fill: getNodeColor(node),
    stroke: isStart
      ? "#16a34a"
      : isEnd
        ? "#ef4444"
        : selected
          ? "#1D2129"
          : isolated
            ? "#d946ef"
            : "#fff",
    // 孤立体系：品红虚线环（未接入主路网）
    dash: isolated && !highlighted ? [3, 2] : undefined,
    strokeWidth: highlighted || isolated ? 3 : 1,
    shadowEnabled: !layeredMode.value,
    shadowColor: "rgba(0,0,0,0.15)",
    shadowBlur: 6,
    shadowOffsetY: 1,
    perfectDrawEnabled: false,
    listening: true,
    hitStrokeWidth: 10,
  };
}

function getNodeTextConfig(node: MapNode) {
  const selected = selectedNode.value?.id === node.id;
  return {
    x: 0,
    y: nodeRadius.value + (layeredMode.value ? 5 : 14),
    text: node.name,
    fontSize: layeredMode.value ? 10 : 12,
    fontFamily: '"PingFang SC", "Microsoft YaHei", sans-serif',
    fill: selected ? "#1D2129" : "#4E5969",
    stroke: "rgba(255,255,255,0.94)",
    strokeWidth: layeredMode.value ? 3 : 0,
    fillAfterStrokeEnabled: true,
    align: "center",
    width: Math.max(nodeRadius.value * 4, 80),
    offsetX: Math.max(nodeRadius.value * 2, 40),
    offsetY: 0,
    listening: false,
    perfectDrawEnabled: false,
  };
}

function getEdgeConfig(edge: MapEdge) {
  const from = getNodeById(edge.nodeAId);
  const to = getNodeById(edge.nodeBId);
  let points: number[] = [];
  if (Array.isArray(edge.path) && edge.path.length >= 2) {
    points = edge.path.flatMap((point: number[]) => {
      const projected = geoPoint(point[0] ?? 0, point[1] ?? 0);
      return [projected.x, projected.y];
    });
  } else {
    const a = from ? nodePos(from) : { x: 0, y: 0 };
    const b = to ? nodePos(to) : { x: 0, y: 0 };
    points = from && to ? [a.x, a.y, b.x, b.y] : [0, 0, 0, 0];
  }
  const isSelected = selectedEdge.value?.id === edge.id;
  return {
    id: `edge-${edge.id}`,
    points: simplifyScreenPoints(points, 48),
    stroke: getEdgeColor(edge),
    strokeWidth: isSelected ? 4 : layeredMode.value ? 1 : 2,
    opacity: layeredMode.value && !isSelected ? 0.72 : 1,
    lineCap: "round",
    hitStrokeWidth: 12,
    perfectDrawEnabled: false,
    shadowForStrokeEnabled: false,
    name: `edge-${edge.id}`,
  };
}

const edgesWithDistance = computed(() => {
  // 路网打断后一条线会被切成很多小段，逐段标公里数既看不清也拖慢渲染
  if (layeredMode.value || visibleEdges.value.length > 300) return [];
  return visibleEdges.value.filter((e) => typeof e.distance === "number" && e.distance > 0);
});

function getEdgeLabelGroupConfig(edge: MapEdge) {
  const from = getNodeById(edge.nodeAId);
  const to = getNodeById(edge.nodeBId);
  if (!from || !to) return { x: 0, y: 0 };
  const a = nodePos(from);
  const b = nodePos(to);
  return {
    x: (a.x + b.x) / 2,
    y: (a.y + b.y) / 2,
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

// 删除前拉 impact：不可删除则中止；拉取失败按普通删除确认处理
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

/** 点到线段的平面距离（坐标单位，用于「离路网多远」判定） */
function pointSegmentDistance(px: number, py: number, ax: number, ay: number,
                              bx: number, by: number): number {
  const dx = bx - ax;
  const dy = by - ay;
  const lengthSquared = dx * dx + dy * dy;
  const t = lengthSquared > 0
    ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / lengthSquared))
    : 0;
  return Math.hypot(px - (ax + dx * t), py - (ay + dy * t));
}

/**
 * 路网接入分析：标出没接上「主路网」的节点（孤立体系）。
 *
 * 判定口径 = **连通性**，不是「离公路多远」：
 * 只要一个点顺着任意路线（公路/铁路/航空/水运都算）能走到主路网上的点，它就不算孤立——
 * 中间经过多少个点、绕多远都不影响。锚定按连通块传播：块里只要有一个港口/车站够得着
 * 主路网、或者块内线路本身贴着主公路（折线接触），整块都算已接入。
 */
function computeIsolation(): void {
  const groundTypes = new Set(
    pathTypes.value.filter((item) => /公路|陆路/.test(item.name)).map((item) => item.id),
  );
  const linkEdges = edges.value.filter(
    (edge) => edge.pathTypeId != null && edge.nodeAId !== edge.nodeBId,
  );
  const roadEdges = linkEdges.filter(
    (edge) => edge.pathTypeId != null && groundTypes.has(edge.pathTypeId),
  );
  if (!linkEdges.length) {
    isolatedNodes.value = new Set();
    return;
  }

  const parent = new Map<number, number>();
  // 带路径压缩的并查集：之前用固定次数的循环找根，连通链一长就会找错根，
  // 主连通块会被算小、孤立节点被误标。
  const find = (id: number): number => {
    let root = id;
    while ((parent.get(root) ?? root) !== root) {
      root = parent.get(root) ?? root;
    }
    let cursor = id;
    while (cursor !== root) {
      const next = parent.get(cursor) ?? root;
      parent.set(cursor, root);
      cursor = next;
    }
    return root;
  };
  // 所有交通方式一起连通：铁路/水路/航线接上的点同样「不孤立」
  for (const edge of linkEdges) {
    if (!parent.has(edge.nodeAId)) parent.set(edge.nodeAId, edge.nodeAId);
    if (!parent.has(edge.nodeBId)) parent.set(edge.nodeBId, edge.nodeBId);
    const left = find(edge.nodeAId);
    const right = find(edge.nodeBId);
    if (left !== right) parent.set(left, right);
  }
  const sizes = new Map<number, number>();
  for (const id of parent.keys()) {
    const root = find(id);
    sizes.set(root, (sizes.get(root) ?? 0) + 1);
  }
  let mainRoot = -1;
  let mainSize = 0;
  for (const [root, size] of sizes) {
    if (size > mainSize) {
      mainRoot = root;
      mainSize = size;
    }
  }
  const connected = new Set<number>();
  for (const id of parent.keys()) {
    if (find(id) === mainRoot) connected.add(id);
  }

  // 主路网的公路线段按「接驳范围」大小的格子分桶（接驳只可能走公路）
  // 接驳范围：35 个地图单位（像素图 1 单位≈1km）/ 0.35°（≈39km）。与导航共用同一个上限。
  const limit = geoMetric.value ? 0.35 : 35;
  const cell = limit > 0 ? limit : 1;
  const grid = new Map<string, number[][]>();
  for (const edge of roadEdges) {
    if (!connected.has(edge.nodeAId) || !connected.has(edge.nodeBId)) continue;
    const points = Array.isArray(edge.path) && edge.path.length >= 2
      ? edge.path
      : [];
    for (let i = 0; i < points.length - 1; i += 1) {
      const a = points[i] ?? [0, 0];
      const b = points[i + 1] ?? [0, 0];
      const ax = Number(a[0]) || 0;
      const ay = Number(a[1]) || 0;
      const bx = Number(b[0]) || 0;
      const by = Number(b[1]) || 0;
      for (let gx = Math.floor(Math.min(ax, bx) / cell); gx <= Math.floor(Math.max(ax, bx) / cell); gx += 1) {
        for (let gy = Math.floor(Math.min(ay, by) / cell); gy <= Math.floor(Math.max(ay, by) / cell); gy += 1) {
          const key = `${gx}:${gy}`;
          const bucket = grid.get(key);
          if (bucket) bucket.push([ax, ay, bx, by]);
          else grid.set(key, [[ax, ay, bx, by]]);
        }
      }
    }
  }

  // 每个点「能不能开到主路网」
  const withinAccess = new Set<number>();
  for (const node of nodes.value) {
    if (connected.has(node.id)) continue;
    const gx = Math.floor(node.x / cell);
    const gy = Math.floor(node.y / cell);
    let nearest = Infinity;
    for (let dx = -1; dx <= 1 && nearest > limit; dx += 1) {
      for (let dy = -1; dy <= 1 && nearest > limit; dy += 1) {
        const bucket = grid.get(`${gx + dx}:${gy + dy}`);
        if (!bucket) continue;
        for (const segment of bucket) {
          const distance = pointSegmentDistance(
            node.x, node.y, segment[0] ?? 0, segment[1] ?? 0, segment[2] ?? 0, segment[3] ?? 0);
          if (distance < nearest) nearest = distance;
        }
      }
    }
    if (nearest <= limit) withinAccess.add(node.id);
  }

  // 锚定是按「连通块」算的：块里只要有一个点接上了主路网（在主连通块里，或在接驳范围内
  // 能开到主路网），整块都算已接入——水运/铁路子网络靠一个港口、一个车站就能连上陆地，
  // 不能因为其余站点离公路远就把整条水系标成孤立。
  const anchored = new Set<number>();
  for (const id of parent.keys()) {
    if (connected.has(id) || withinAccess.has(id)) anchored.add(find(id));
  }
  for (const id of withinAccess) {
    if (!parent.has(id)) anchored.add(-id);
  }

  // 还有一种「看着就是连着」的情况：水路线/铁路线本身贴着公路跑（折线压到公路上）。
  // 只按港口节点算距离会漏掉它，于是整条水系被判成孤立，和地图上看到的不一致。
  const contactLimit = Math.max(1e-6, limit * 0.1);
  const pointTouchesMainRoad = (x: number, y: number): boolean => {
    const gx = Math.floor(x / cell);
    const gy = Math.floor(y / cell);
    for (let dx = -1; dx <= 1; dx += 1) {
      for (let dy = -1; dy <= 1; dy += 1) {
        const bucket = grid.get(`${gx + dx}:${gy + dy}`);
        if (!bucket) continue;
        for (const segment of bucket) {
          const distance = pointSegmentDistance(
            x, y, segment[0] ?? 0, segment[1] ?? 0, segment[2] ?? 0, segment[3] ?? 0);
          if (distance <= contactLimit) return true;
        }
      }
    }
    return false;
  };
  for (const edge of linkEdges) {
    const fromRoot = find(edge.nodeAId);
    const toRoot = find(edge.nodeBId);
    if (anchored.has(fromRoot) && anchored.has(toRoot)) continue;
    const points = Array.isArray(edge.path) && edge.path.length >= 2 ? edge.path : [];
    for (const point of points) {
      const x = Number(point[0]) || 0;
      const y = Number(point[1]) || 0;
      if (!pointTouchesMainRoad(x, y)) continue;
      anchored.add(fromRoot);
      anchored.add(toRoot);
      break;
    }
  }

  const isolated = new Set<number>();
  for (const node of nodes.value) {
    // 矿点/行政区域划分这类本来就不参与运输的节点不标（导航也选不到它们）
    if (!isNavSelectable(node)) continue;
    const root = parent.has(node.id) ? find(node.id) : -node.id;
    if (anchored.has(root)) continue;
    isolated.add(node.id);
  }
  isolatedNodes.value = isolated;
}

/** 画布坐标：经纬度 → 舞台像素（GEO 模式） */
function geoPoint(lon: number, lat: number): { x: number; y: number } {
  const g = geoView.value;
  if (!g) return { x: lon, y: lat };
  return {
    x: g.x + (lon - g.minLon) * g.scale,
    y: g.y + (g.maxLat - lat) * g.scale,
  };
}

/** 屏幕坐标抽稀：大地图缩放重绘时大幅减少顶点数 */
function simplifyScreenPoints(points: number[], maxPoints: number): number[] {
  const count = Math.floor(points.length / 2);
  if (count <= maxPoints) return points;
  const step = Math.ceil(count / maxPoints);
  const result: number[] = [];
  for (let index = 0; index < count; index += step) {
    result.push(points[index * 2] ?? 0, points[index * 2 + 1] ?? 0);
  }
  const lastX = points[(count - 1) * 2];
  const lastY = points[(count - 1) * 2 + 1];
  if (lastX !== undefined && lastY !== undefined) result.push(lastX, lastY);
  return result;
}

const visibleNodes = computed(() =>
  nodes.value.filter((node) => !hiddenNodeTypes.value.includes(node.nodeTypeId ?? -1)),
);
/** 当前可见的孤立节点数（图例用，跟着图层开关变） */
const isolatedVisibleCount = computed(() => {
  const isolated = isolatedNodes.value;
  return visibleNodes.value.filter((node) => isolated.has(node.id)).length;
});
const visibleEdges = computed(() =>
  edges.value.filter((edge) => !hiddenPathTypes.value.includes(edge.pathTypeId ?? -1)),
);
const polygonLayers = computed(() =>
  mapLayers.value.filter(
    (layer) =>
      layer.kind === "POLYGON" &&
      layer.features.length > 0 &&
      !hiddenLayers.value.includes(layer.name),
  ),
);

const layeredMode = computed(() => mapLayers.value.length > 3);
const nodeRadius = computed(() => (layeredMode.value ? 5 : NODE_RADIUS));
const showNodeNames = ref(true);
const LABEL_NODE_TYPES = new Set([
  "城市点位",
  "机场",
  "码头",
  "火车站",
  "行政区域划分",
  "高速口",
  "矿点",
]);
// 导航起终点不接受的节点类型
const NAV_EXCLUDED_TYPES = new Set(["矿点", "默认节点", "线路端点", "行政区域划分", "城市点位"]);
const AUTO_NODE_NAME = /^节点\s*[（(]/;

function isNavSelectable(node: MapNode): boolean {
  if (AUTO_NODE_NAME.test(node.name || "")) return false;
  const typeName = nodeTypes.value.find((type) => type.id === node.nodeTypeId)?.name;
  return !typeName || !NAV_EXCLUDED_TYPES.has(typeName);
}

/** 导航结果里只展示有业务名称的节点，自动端点/默认节点仅作为内部拓扑使用 */
function isDisplayRouteNode(node: MapNode): boolean {
  if (AUTO_NODE_NAME.test(node.name || "")) return false;
  const typeName = nodeTypes.value.find((type) => type.id === node.nodeTypeId)?.name;
  return typeName !== "默认节点" && typeName !== "线路端点";
}

function shouldShowNodeLabel(node: MapNode): boolean {
  if (selectedNode.value?.id === node.id) return true;
  if (navStart.value?.id === node.id || navEnd.value?.id === node.id) return true;
  if (AUTO_NODE_NAME.test(node.name || "")) return false;
  if (!showNodeNames.value) return false;
  if (!layeredMode.value) return true;
  const typeName = nodeTypes.value.find((type) => type.id === node.nodeTypeId)?.name;
  return typeName ? LABEL_NODE_TYPES.has(typeName) : false;
}

function toggleNav(): void {
  navMode.value = !navMode.value;
  if (!navMode.value) clearNav();
}

function clearNav(): void {
  navStart.value = null;
  navEnd.value = null;
  navRoute.value = null;
  navError.value = "";
}

function swapNav(): void {
  if (!navStart.value || !navEnd.value) return;
  const start = navStart.value;
  navStart.value = navEnd.value;
  navEnd.value = start;
  computeRoute();
}

function onNodeClick(node: MapNode): void {
  if (panMoved) return;
  if (!navMode.value) {
    selectNode(node);
    return;
  }
  if (!isNavSelectable(node)) {
    ElMessage.info("该节点不参与导航，请选择公路/铁路/航空/水运上的节点");
    return;
  }
  selectNode(node);
  if (!navStart.value || (navStart.value && navEnd.value)) {
    navStart.value = node;
    navEnd.value = null;
    navRoute.value = null;
    navError.value = "";
    return;
  }
  if (navStart.value.id === node.id) return;
  navEnd.value = node;
  computeRoute();
}

function pathTypeName(pathTypeId?: number | null): string {
  return pathTypes.value.find((item) => item.id === pathTypeId)?.name || "线路";
}

/** 按交通方式汇总里程：公路干线+支线合并为「公路」 */
const navModeSummary = computed(() => {
  const totals = new Map<string, number>();
  for (const edge of navRoute.value?.edges || []) {
    let label: string;
    if (edge.id < 0) {
      // 接驳段就是「开到最近的公路」，本质仍是公路里程，汇总时并入「公路」
      label = "公路";
    } else {
      const name = pathTypeName(edge.pathTypeId);
      if (name.includes("公路")) label = "公路";
      else if (name.includes("航空")) label = "航空";
      else if (name.includes("铁路")) label = "铁路";
      else if (name.includes("水路")) label = "水运";
      else label = name || "其他";
    }
    totals.set(label, (totals.get(label) || 0) + (Number(edge.distance) || 0));
  }
  return [...totals].map(([label, distance]) => ({ label, distance }));
});

interface NavLink {
  to: string;
  groupId: number;
  pathTypeId: number | null;
  distance: number;
  path: number[][];
}

interface NavVertex {
  key: string;
  x: number;
  y: number;
  node?: MapNode;
}

type Pt = [number, number];

/** 折线上的点统一成二元组，避免 noUncheckedIndexedAccess 到处 ?? 0 */
function asPt(value: number[] | undefined): Pt {
  return [value?.[0] ?? 0, value?.[1] ?? 0];
}

/** 两点间距离：GEO 模式按球面 km（与导入时算的边里程同一口径），像素地图 1 单位≈1km */
function distanceKm(a: Pt, b: Pt): number {
  if (!geoMetric.value) return Math.hypot(b[0] - a[0], b[1] - a[1]);
  const toRad = Math.PI / 180;
  const dLat = (b[1] - a[1]) * toRad;
  const dLon = (b[0] - a[0]) * toRad;
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(a[1] * toRad) * Math.cos(b[1] * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * 6371.0088 * Math.asin(Math.min(1, Math.sqrt(h)));
}

function lineLengthKm(points: number[][]): number {
  let total = 0;
  for (let i = 0; i < points.length - 1; i += 1) {
    total += distanceKm(asPt(points[i]), asPt(points[i + 1]));
  }
  return total;
}

/** 折线的坐标平面累计弧长：接驳点要按位置插进边的折线里 */
function cumulativeUnits(points: number[][]): number[] {
  const result: number[] = [0];
  let total = 0;
  for (let i = 0; i < points.length - 1; i += 1) {
    const a = asPt(points[i]);
    const b = asPt(points[i + 1]);
    total += Math.hypot(b[0] - a[0], b[1] - a[1]);
    result.push(total);
  }
  return result;
}

/** 取折线上 [fromPos, toPos] 的一段，两端用算好的精确点 */
function slicePolyline(
  points: number[][],
  cumulative: number[],
  fromPos: number,
  toPos: number,
  startPoint: number[],
  endPoint: number[],
): number[][] {
  const result: number[][] = [startPoint];
  for (let i = 1; i < points.length - 1; i += 1) {
    const point = points[i];
    if (point && (cumulative[i] ?? 0) > fromPos && (cumulative[i] ?? 0) < toPos) {
      result.push(point);
    }
  }
  result.push(endPoint);
  return result;
}

function computeRoute(): void {
  navError.value = "";
  const start = navStart.value;
  const end = navEnd.value;
  if (!start || !end) return;
  if (start.id === end.id) {
    navError.value = "起点和终点不能是同一个节点";
    navRoute.value = null;
    return;
  }
  const allowed = new Set(navTypeIds.value);
  if (!allowed.size) {
    navError.value = "请至少选择一种交通方式";
    navRoute.value = null;
    return;
  }

  const vertices = new Map<string, NavVertex>();
  const adjacency = new Map<string, NavLink[]>();
  const nodeKey = (nodeId: number) => `n${nodeId}`;
  const ensureVertex = (key: string, x: number, y: number): NavVertex => {
    let vertex = vertices.get(key);
    if (!vertex) {
      vertex = { key, x, y };
      vertices.set(key, vertex);
    }
    return vertex;
  };
  const addLink = (
    from: string,
    to: string,
    path: number[][],
    groupId: number,
    pathTypeId: number | null,
    distance: number,
  ) => {
    if (from === to) return;
    if (!adjacency.has(from)) adjacency.set(from, []);
    if (!adjacency.has(to)) adjacency.set(to, []);
    adjacency.get(from)?.push({ to, groupId, pathTypeId, distance, path });
    adjacency.get(to)?.push({ to: from, groupId, pathTypeId, distance, path: [...path].reverse() });
  };

  // 路网 = 地图边本身。导入/重建时已经做过「端点吸附 + T 型接头 + 交点打断」，
  // 每条边就是两个节点之间的一段路，距离直接用服务端存的公里数——
  // 不再对折线采样、也不再靠 20×15 网格猜连通（那会把里程算短、路线跳线）。
  interface NavEdge {
    id: number;
    from: MapNode;
    to: MapNode;
    points: number[][];
    distance: number;
    units: number;
    cumulative: number[];
    pathTypeId: number | null;
  }
  // 接驳只能走「陆路」：机场/码头是靠节点接入航空线/水路线的，
  // 不能把城市点位、高速口直接投影到一条航线上（那会造出半路换乘）。
  const groundTypes = new Set(
    pathTypes.value.filter((item) => /公路|陆路/.test(item.name)).map((item) => item.id),
  );
  const usable: NavEdge[] = [];
  const onGraph = new Set<string>();
  const onRoad = new Set<string>();
  for (const edge of edges.value) {
    if (edge.pathTypeId == null || !allowed.has(edge.pathTypeId)) continue;
    if (edge.nodeAId === edge.nodeBId) continue; // 回环保留绘制，但不参与寻路
    const from = getNodeById(edge.nodeAId);
    const to = getNodeById(edge.nodeBId);
    if (!from || !to) continue;
    const points =
      Array.isArray(edge.path) && edge.path.length >= 2
        ? edge.path.map((point) => [Number(point[0]) || 0, Number(point[1]) || 0])
        : [
            [from.x, from.y],
            [to.x, to.y],
          ];
    const cumulative = cumulativeUnits(points);
    const units = cumulative[cumulative.length - 1] ?? 0;
    const stored = Number(edge.distance);
    usable.push({
      id: edge.id,
      from,
      to,
      points,
      cumulative,
      units,
      distance: stored > 0 ? stored : lineLengthKm(points),
      pathTypeId: edge.pathTypeId,
    });
    onGraph.add(nodeKey(from.id));
    onGraph.add(nodeKey(to.id));
    if (edge.pathTypeId != null && groundTypes.has(edge.pathTypeId)) {
      onRoad.add(nodeKey(from.id));
      onRoad.add(nodeKey(to.id));
    }
  }
  for (const item of usable) {
    ensureVertex(nodeKey(item.from.id), item.from.x, item.from.y).node = item.from;
    ensureVertex(nodeKey(item.to.id), item.to.x, item.to.y).node = item.to;
  }

  // 接驳：起终点不在路网上（机场/码头/城市点位没有连线）时，投影到最近的一条路，
  // 并在投影处把那条边切开，接驳里程按真实垂直距离计。
  interface EdgeSplit {
    position: number;
    point: number[];
    key: string;
    node: MapNode;
    gap: number;
  }
  const splits = new Map<number, EdgeSplit[]>();
  const accessLimit = geoMetric.value ? 0.35 : 35;
  // 可接驳的陆路段摊平成一维表：机场/码头也要各自找最近公路，逐条边遍历太慢
  const groundSegments: Array<{ item: NavEdge; index: number; a: Pt; b: Pt }> = [];
  for (const item of usable) {
    if (!(item.units > 0)) continue;
    if (item.pathTypeId == null || !groundTypes.has(item.pathTypeId)) continue;
    for (let i = 0; i < item.points.length - 1; i += 1) {
      groundSegments.push({
        item,
        index: i,
        a: asPt(item.points[i]),
        b: asPt(item.points[i + 1]),
      });
    }
  }
  const attach = (node: MapNode): boolean => {
    const key = nodeKey(node.id);
    ensureVertex(key, node.x, node.y).node = node;
    if (onRoad.has(key)) return true;              // 已经在公路网上，不需要接驳
    if (!groundSegments.length) return onGraph.has(key); // 没勾陆路：只能靠航线/水运
    const point: Pt = [node.x, node.y];
    let best: { item: NavEdge; position: number; point: number[]; gap: number } | null = null;
    for (const segment of groundSegments) {
      const { a, b } = segment;
      const dx = b[0] - a[0];
      const dy = b[1] - a[1];
      const lengthSquared = dx * dx + dy * dy;
      const t =
        lengthSquared > 0
          ? Math.max(
              0,
              Math.min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / lengthSquared),
            )
          : 0;
      const px = a[0] + dx * t;
      const py = a[1] + dy * t;
      const gap = distanceKm(point, [px, py]);
      if (!best || gap < best.gap) {
        best = {
          item: segment.item,
          position: (segment.item.cumulative[segment.index] ?? 0) + Math.sqrt(lengthSquared) * t,
          point: [px, py],
          gap,
        };
      }
    }
    // 接不上公路时：如果节点本来就挂在航线/水路上，仍然可用（纯航空/水运路线）
    if (!best || best.gap > accessLimit || best.gap <= 0.01) {
      return onGraph.has(key);
    }
    const splitKey = `s${best.item.id}:${best.position.toFixed(6)}`;
    ensureVertex(splitKey, best.point[0] ?? 0, best.point[1] ?? 0).node = node;
    const list = splits.get(best.item.id) ?? [];
    list.push({
      position: best.position,
      point: best.point,
      key: splitKey,
      node,
      gap: best.gap,
    });
    splits.set(best.item.id, list);
    return true;
  };
  if (!attach(start)) {
    navError.value = "起点附近没有可用线路（超出接驳范围）";
    navRoute.value = null;
    return;
  }
  if (!attach(end)) {
    navError.value = "终点附近没有可用线路（超出接驳范围）";
    navRoute.value = null;
    return;
  }
  // 多选交通方式时，机场/码头也要能「开车过去再换乘」，不能只有起终点能接驳
  const transferSeen = new Set<number>([start.id, end.id]);
  for (const item of usable) {
    if (item.pathTypeId == null) continue;
    if (!/航空|水路/.test(pathTypeName(item.pathTypeId))) continue;
    for (const node of [item.from, item.to]) {
      if (transferSeen.has(node.id)) continue;
      transferSeen.add(node.id);
      attach(node);
    }
  }

  // 落链：边上按接驳点切开，接驳段单独成段（灰色虚线）
  let accessGroup = -100000;
  for (const item of usable) {
    const list = (splits.get(item.id) ?? []).slice().sort((a, b) => a.position - b.position);
    let cursorKey = nodeKey(item.from.id);
    let cursorPosition = 0;
    let cursorPoint: number[] = item.points[0] ?? [0, 0];
    for (const split of list) {
      const path = slicePolyline(
        item.points,
        item.cumulative,
        cursorPosition,
        split.position,
        cursorPoint,
        split.point,
      );
      const distance =
        item.units > 0 ? (item.distance * (split.position - cursorPosition)) / item.units : 0;
      addLink(cursorKey, split.key, path, item.id, item.pathTypeId, distance);
      addLink(
        nodeKey(split.node.id),
        split.key,
        [
          [split.node.x, split.node.y],
          split.point,
        ],
        accessGroup--,
        null,
        split.gap,
      );
      cursorKey = split.key;
      cursorPosition = split.position;
      cursorPoint = split.point;
    }
    const tailDistance = Math.max(0, item.units - cursorPosition);
    addLink(
      cursorKey,
      nodeKey(item.to.id),
      slicePolyline(
        item.points,
        item.cumulative,
        cursorPosition,
        item.units,
        cursorPoint,
        item.points[item.points.length - 1] ?? [0, 0],
      ),
      item.id,
      item.pathTypeId,
      item.units > 0 ? (item.distance * tailDistance) / item.units : item.distance,
    );
  }

  const startKey = nodeKey(start.id);
  const endKey = nodeKey(end.id);
  if (!adjacency.get(startKey)?.length || !adjacency.get(endKey)?.length) {
    navError.value = "所选节点不在当前交通方式的路网上";
    navRoute.value = null;
    return;
  }

  const costOf = (link: NavLink): number => {
    const distance = Math.max(link.distance, 0.001);
    if (navWeight.value === "nodes") return 1;
    return distance;
  };

  const distances = new Map<string, number>([[startKey, 0]]);
  const prevKey = new Map<string, string>();
  const prevLink = new Map<string, NavLink>();
  const visited = new Set<string>();
  while (visited.size < adjacency.size) {
    let current: string | null = null;
    let currentDistance = Infinity;
    for (const [key, distance] of distances) {
      if (!visited.has(key) && distance < currentDistance) {
        current = key;
        currentDistance = distance;
      }
    }
    if (current === null) break;
    visited.add(current);
    if (current === endKey) break;
    for (const link of adjacency.get(current) || []) {
      if (visited.has(link.to)) continue;
      const nextDistance = currentDistance + costOf(link);
      if (nextDistance < (distances.get(link.to) ?? Infinity)) {
        distances.set(link.to, nextDistance);
        prevKey.set(link.to, current);
        prevLink.set(link.to, link);
      }
    }
  }

  if (!distances.has(endKey)) {
    navError.value = "所选节点之间没有通过路网连通";
    navRoute.value = null;
    return;
  }

  const links: NavLink[] = [];
  let cursor = endKey;
  while (cursor !== startKey) {
    const link = prevLink.get(cursor);
    const previous = prevKey.get(cursor);
    if (!link || previous == null) break;
    links.push(link);
    cursor = previous;
  }
  links.reverse();

  const routeEdges: MapEdge[] = [];
  let index = 0;
  while (index < links.length) {
    const first = links[index];
    if (!first) break;
    const path = first.path.map((point) => [...point]);
    let distance = first.distance;
    const groupId = first.groupId;
    const pathTypeId = first.pathTypeId;
    const isLand = groupId <= -300000;
    index += 1;
    if (groupId >= 0 || isLand) {
      while (index < links.length) {
        const next = links[index];
        if (!next) break;
        const sameKind = isLand
          ? next.groupId <= -300000
          : next.groupId >= 0 && next.pathTypeId === pathTypeId;
        if (!sameKind) break;
        distance += next.distance;
        const nextPath = next.path;
        if (path.length && nextPath.length) {
          const last = path[path.length - 1];
          const startPoint = nextPath[0];
          path.push(...nextPath.slice(
            last && startPoint && last[0] === startPoint[0] && last[1] === startPoint[1] ? 1 : 0,
          ));
        }
        index += 1;
      }
    }
    routeEdges.push({
      id: groupId,
      nodeAId: -1,
      nodeBId: -1,
      pathTypeId,
      distance,
      path,
      relations: {},
    } as MapEdge);
  }

  // 途经节点：按路段类型只标记允许的节点
  const routePath: number[][] = [];
  const ranges: Array<{ start: number; end: number; mode: string; startPoint: number[]; endPoint: number[] }> = [];
  for (const edge of routeEdges) {
    const startIndex = routePath.length;
    for (const point of edge.path || []) {
      const previous = routePath[routePath.length - 1];
      if (!previous || previous[0] !== point[0] || previous[1] !== point[1]) {
        routePath.push([point[0] ?? 0, point[1] ?? 0]);
      }
    }
    const endIndex = routePath.length - 1;
    if (endIndex > startIndex) {
      ranges.push({
        start: startIndex,
        end: endIndex,
        mode: edge.id <= -300000 ? "陆路" : pathTypeName(edge.pathTypeId),
        startPoint: routePath[startIndex] ?? [0, 0],
        endPoint: routePath[endIndex] ?? [0, 0],
      });
    }
  }

  const routeNodes: MapNode[] = [start];
  if (ranges.length) {
    const candidates = nodes.value
      .filter((node) => node.id !== start.id && node.id !== end.id)
      .filter((node) => isNavSelectable(node) && isDisplayRouteNode(node))
      .map((node) => {
        const nodeType = nodeTypes.value.find((type) => type.id === node.nodeTypeId)?.name || "";
        let bestDistance = Infinity;
        let bestProgress = Infinity;
        let bestRange: (typeof ranges)[number] | null = null;
        for (const range of ranges) {
          for (let i = range.start; i < range.end; i += 1) {
            const a = routePath[i] ?? [0, 0];
            const b = routePath[i + 1] ?? [0, 0];
            const dx = (b[0] ?? 0) - (a[0] ?? 0);
            const dy = (b[1] ?? 0) - (a[1] ?? 0);
            const lengthSquared = dx * dx + dy * dy || 1;
            const t = Math.max(0, Math.min(1,
              ((node.x - (a[0] ?? 0)) * dx + (node.y - (a[1] ?? 0)) * dy) / lengthSquared));
            const px = (a[0] ?? 0) + dx * t;
            const py = (a[1] ?? 0) + dy * t;
            const distance = Math.hypot(node.x - px, node.y - py);
            if (distance < bestDistance) {
              bestDistance = distance;
              bestProgress = i + t;
              bestRange = range;
            }
          }
        }
        if (!bestRange || bestDistance > 12) return null;
        const nearRoadEndpoint = Math.min(
          Math.hypot(node.x - (bestRange.startPoint[0] ?? 0), node.y - (bestRange.startPoint[1] ?? 0)),
          Math.hypot(node.x - (bestRange.endPoint[0] ?? 0), node.y - (bestRange.endPoint[1] ?? 0)),
        ) <= 12;
        let allowed = false;
        if (bestRange.mode.includes("航空")) allowed = nodeType === "机场";
        else if (bestRange.mode.includes("水路")) allowed = nodeType === "码头";
        else if (bestRange.mode.includes("铁路")) allowed = nodeType === "火车站";
        else if (bestRange.mode.includes("公路") || bestRange.mode.includes("陆路")) allowed = nearRoadEndpoint;
        return allowed ? { node, progress: bestProgress } : null;
      })
      .filter((item): item is { node: MapNode; progress: number } => item !== null)
      .sort((a, b) => a.progress - b.progress);
    for (const item of candidates) {
      if (routeNodes[routeNodes.length - 1]?.id !== item.node.id) {
        routeNodes.push(item.node);
      }
    }
  }
  if (routeNodes[routeNodes.length - 1]?.id !== end.id) routeNodes.push(end);

  navRoute.value = {
    nodes: routeNodes,
    edges: routeEdges,
    distance: links.reduce((sum, link) => sum + (Number(link.distance) || 0), 0),
  };
}

function getRouteLineConfig(edge: MapEdge) {
  const from = getNodeById(edge.nodeAId);
  const to = getNodeById(edge.nodeBId);
  let points: number[] = [];
  if (Array.isArray(edge.path) && edge.path.length >= 2) {
    const raw = edge.path.flatMap((point: number[]) => {
      const projected = geoPoint(point[0] ?? 0, point[1] ?? 0);
      return [projected.x, projected.y];
    });
    points = simplifyScreenPoints(raw, 80);
  } else {
    const a = from ? nodePos(from) : { x: 0, y: 0 };
    const b = to ? nodePos(to) : { x: 0, y: 0 };
    points = [a.x, a.y, b.x, b.y];
  }
  const isAccess = edge.id < 0;
  const isLand = edge.id <= -300000;
  return {
    points,
    stroke: isLand ? "#16a34a" : isAccess ? "#9ca3af" : "#f59e0b",
    strokeWidth: isLand ? 4 : isAccess ? 3 : 5,
    dash: isAccess && !isLand ? [7, 5] : undefined,
    opacity: isAccess ? 0.9 : 0.95,
    lineCap: "round",
    listening: false,
    perfectDrawEnabled: false,
    shadowColor: isLand || !isAccess ? "#f59e0b" : "",
    shadowBlur: isAccess && !isLand ? 0 : 5,
  };
}

function toggleNodeType(id: number) {
  hiddenNodeTypes.value = hiddenNodeTypes.value.includes(id)
    ? hiddenNodeTypes.value.filter((value) => value !== id)
    : [...hiddenNodeTypes.value, id];
}

function togglePathType(id: number) {
  hiddenPathTypes.value = hiddenPathTypes.value.includes(id)
    ? hiddenPathTypes.value.filter((value) => value !== id)
    : [...hiddenPathTypes.value, id];
}

function toggleLayer(name: string) {
  hiddenLayers.value = hiddenLayers.value.includes(name)
    ? hiddenLayers.value.filter((value) => value !== name)
    : [...hiddenLayers.value, name];
}

function getPolygonConfig(
  feature: MapLayerSetting["features"][number],
  layer: MapLayerSetting,
) {
  const isRegion = layer.role === "REGION";
  const ring = feature.rings[0] || [];
  const points = ring.flatMap((point: number[]) => {
    const projected = geoPoint(point[0] ?? 0, point[1] ?? 0);
    return [projected.x, projected.y];
  });
  return {
    points: simplifyScreenPoints(points, 140),
    closed: true,
    fill: isRegion ? layer.color || "#7FB3D5" : feature.color || layer.color || "#7FB3D5",
    opacity: isRegion ? 0.58 : 0.42,
    stroke: isRegion ? "" : layer.color || "#7FB3D5",
    strokeWidth: isRegion ? 0 : 1.2,
    hitStrokeWidth: 8,
    listening: true,
    perfectDrawEnabled: false,
  };
}

function getPolygonLabelConfig(
  feature: MapLayerSetting["features"][number],
  layer: MapLayerSetting,
) {
  // 省份只保留整块背景，不再显示细分城市小区域名称
  if (layer.role === "REGION") return { text: "" };
  const ring = feature.rings[0] || [];
  if (!ring.length || !feature.name) return { text: "" };
  const sum = ring.reduce(
    (acc: { x: number; y: number }, point: number[]) => {
      const projected = geoPoint(point[0] ?? 0, point[1] ?? 0);
      return { x: acc.x + projected.x, y: acc.y + projected.y };
    },
    { x: 0, y: 0 },
  );
  return {
    x: sum.x / ring.length,
    y: sum.y / ring.length - 6,
    text: feature.name,
    fontSize: 10,
    fill: "#374151",
    opacity: 0.72,
    listening: false,
  };
}

function pickRegion(feature: MapLayerSetting["features"][number]) {
  if (panMoved) return;
  pickedRegion.value = feature.region || feature.name || "";
}

function clearPickedRegion() {
  pickedRegion.value = "";
}

async function loadAllMapRows<T>(
  loader: (params: { page: number; pageSize: number }) => Promise<{ items: T[]; total: number }>,
  pageSize = 500,
): Promise<T[]> {
  const first = await loader({ page: 1, pageSize });
  const items = [...first.items];
  let page = 1;
  while (items.length < first.total && first.items.length > 0) {
    page += 1;
    const next = await loader({ page, pageSize });
    if (!next.items.length) break;
    items.push(...next.items);
  }
  return items;
}

async function loadData() {
  loading.value = true;
  try {
    if (!props.cid) {
      nodes.value = [];
      edges.value = [];
      nodeTypes.value = [];
      pathTypes.value = [];
      regions.value = [];
      regionIdMap.value = new Map();
      mapMode.value = "PIXEL";
      mapBounds.value = [];
      return;
    }
    // 地图数据量大时接口单页上限 500，必须分页取全，否则缺失节点会让连线/导航断开
    const [typeRes, pathRes, nodeRows, edgeRows, settings] = await Promise.all([
      mapNodeTypeApi.list(props.cid, { pageSize: 500 }),
      pathTypeApi.list(props.cid, { pageSize: 500 }),
      loadAllMapRows<MapNode>((params) => mapNodeApi.list(props.cid, params)),
      loadAllMapRows<MapEdge>((params) => mapEdgeApi.list(props.cid, params)),
      getMapSettings(props.cid).catch(() => null),
    ]);
    nodeTypes.value = typeRes.items || [];
    pathTypes.value = pathRes.items || [];
    const allPathTypeIds = pathTypes.value.map((item) => item.id);
    if (!navTypesInitialized.value) {
      navTypeIds.value = allPathTypeIds;
      navTypesInitialized.value = true;
    } else {
      navTypeIds.value = navTypeIds.value.filter((id) => allPathTypeIds.includes(id));
      if (!navTypeIds.value.length) navTypeIds.value = allPathTypeIds;
    }
    nodes.value = nodeRows;
    // basedata 接口地图边字段是 fromNodeId/toNodeId；画布/导航统一用 nodeAId/nodeBId
    edges.value = edgeRows.map((edge) => ({
      ...edge,
      nodeAId: edge.nodeAId ?? (edge as any).fromNodeId,
      nodeBId: edge.nodeBId ?? (edge as any).toNodeId,
    }));
    dragPos.value = {};
    mapMode.value = settings?.mode === "GEO" ? "GEO" : "PIXEL";
    mapBounds.value = settings?.bounds ?? [];
    mapLayers.value = settings?.layers ?? [];
    hiddenNodeTypes.value = mapLayers.value
      .filter((layer) => layer.kind === "POINT" && !layer.visible && layer.nodeTypeId != null)
      .map((layer) => layer.nodeTypeId as number);
    hiddenPathTypes.value = mapLayers.value
      .filter((layer) => layer.kind === "LINE" && !layer.visible && layer.pathTypeId != null)
      .map((layer) => layer.pathTypeId as number);
    hiddenLayers.value = mapLayers.value
      .filter((layer) => layer.kind === "POLYGON" && !layer.visible)
      .map((layer) => layer.name);
    // 矿点、行政区域划分只是背景信息（不参与运输、导航也选不到），默认不显示；
    // 城市点位默认也不显示（车站/机场/码头等按需在图例里勾开）；
    // 想看的时候在图例里勾上即可，刷新后会回到默认隐藏。
    for (const name of ["矿点", "行政区域划分", "城市点位"]) {
      const type = nodeTypes.value.find((item) => item.name === name);
      if (type && !hiddenNodeTypes.value.includes(type.id)) {
        hiddenNodeTypes.value = [...hiddenNodeTypes.value, type.id];
      }
    }
    // 多图层工程 / 打断后的路网会产生大量「默认节点」（交点、线路端点），
    // 数量一多就默认隐藏，避免把城市/机场淹没在一片小圆点里
    const endpointType = nodeTypes.value.find((type) => type.name === "默认节点");
    const autoNodeCount = endpointType
      ? nodes.value.filter((node) => node.nodeTypeId === endpointType.id).length
      : 0;
    if (endpointType && (layeredMode.value || autoNodeCount > 200)
        && !hiddenNodeTypes.value.includes(endpointType.id)) {
      hiddenNodeTypes.value = [...hiddenNodeTypes.value, endpointType.id];
    }
    computeIsolation();
    await loadRegionsFromServer();
    // 节点就绪即锚定背景框，与图片加载解耦，避免重进界面错位
    recomputeBBoxIfAuto();
  } catch (err) {
    ElMessage.error(errorMessage(err, "操作失败"));
  } finally {
    loading.value = false;
  }
}

// 事件参数仅用于保持回调签名一致（坐标换算不依赖它）
// eslint-disable-next-line @typescript-eslint/no-unused-vars
function getCanvasPos(_e: any) {
  const stage = stageRef.value?.getStage();
  if (!stage) return { x: 0, y: 0 };
  const pos = stage.getPointerPosition();
  return { x: pos?.x || 0, y: pos?.y || 0 };
}

function startGpuPanAt(clientX: number, clientY: number) {
  if (zoomPreviewActive) commitGpuZoom();
  const stage = stageRef.value?.getStage();
  if (!stage) return;
  panContainer = stage.container() as HTMLElement;
  panStartX = clientX;
  panStartY = clientY;
  panDx = 0;
  panDy = 0;
  panOriginX = stage.x();
  panOriginY = stage.y();
  isPanning = true;
  panContainer.style.willChange = "transform";
  window.addEventListener("mousemove", handleWindowPanMove);
  window.addEventListener("mouseup", finishGpuPan);
  window.addEventListener("touchmove", handleWindowTouchMove, { passive: false });
  window.addEventListener("touchend", handleWindowTouchEnd);
  window.addEventListener("touchcancel", handleWindowTouchEnd);
}

/** 触屏平移/缩放统一入口：单指拖动平移，双指缩放 */
function handleWindowTouchMove(ev: TouchEvent) {
  if (pinchActive) {
    const first = ev.touches[0];
    const second = ev.touches[1];
    if (!first || !second) return;
    ev.preventDefault();
    const stage = stageRef.value?.getStage();
    const wrapper = canvasWrapper.value;
    const container = stage?.container() as HTMLElement | undefined;
    if (!stage || !wrapper || !container) return;
    const distance = Math.hypot(first.clientX - second.clientX, first.clientY - second.clientY) || 1;
    const nextScale = Math.max(0.2, Math.min(5, zoomBaseScale * (distance / pinchStartDistance)));
    const rect = wrapper.getBoundingClientRect();
    const midX = (first.clientX + second.clientX) / 2 - rect.left;
    const midY = (first.clientY + second.clientY) / 2 - rect.top;
    zoomCurrentScale = nextScale;
    zoomCurrentX = midX - pinchContentX * nextScale;
    zoomCurrentY = midY - pinchContentY * nextScale;
    const k = nextScale / (zoomBaseScale || 1);
    const tx = zoomCurrentX - k * zoomBaseX;
    const ty = zoomCurrentY - k * zoomBaseY;
    container.style.transform = `translate3d(${tx}px, ${ty}px, 0) scale(${k})`;
    return;
  }
  if (!isPanning || !panContainer) return;
  const touch = ev.touches[0];
  if (!touch) return;
  ev.preventDefault();
  panDx = touch.clientX - panStartX;
  panDy = touch.clientY - panStartY;
  if (Math.abs(panDx) > 3 || Math.abs(panDy) > 3) panMoved = true;
  panContainer.style.transform = `translate3d(${panDx}px, ${panDy}px, 0)`;
}

function handleWindowTouchEnd(ev: TouchEvent) {
  if (pinchActive && ev.touches.length < 2) {
    pinchActive = false;
    commitGpuZoom();
  }
  if (ev.touches.length === 0) finishGpuPan();
}

function handleWindowPanMove(ev: MouseEvent) {
  if (!isPanning || !panContainer) return;
  panDx = ev.clientX - panStartX;
  panDy = ev.clientY - panStartY;
  if (Math.abs(panDx) > 3 || Math.abs(panDy) > 3) panMoved = true;
  // 拖动期间只做 GPU 合成位移，不重绘 Canvas
  panContainer.style.transform = `translate3d(${panDx}px, ${panDy}px, 0)`;
}

function finishGpuPan() {
  if (!isPanning) return;
  const stage = stageRef.value?.getStage();
  if (stage && panContainer) {
    stage.x(panOriginX + panDx);
    stage.y(panOriginY + panDy);
    panContainer.style.transform = "";
    panContainer.style.willChange = "";
    stage.batchDraw();
  }
  window.removeEventListener("mousemove", handleWindowPanMove);
  window.removeEventListener("mouseup", finishGpuPan);
  window.removeEventListener("touchmove", handleWindowTouchMove);
  window.removeEventListener("touchend", handleWindowTouchEnd);
  window.removeEventListener("touchcancel", handleWindowTouchEnd);
  isPanning = false;
  panContainer = null;
  setTimeout(() => {
    stageOnMove = false;
  }, 50);
}

/** 命中可拖拽的节点时不要抢走拖拽（编辑态拖节点 = 移动节点，不是平移地图） */
function isNodeDragTarget(target: any): boolean {
  if (!canEdit.value) return false;
  const stage = stageRef.value?.getStage();
  let current = target;
  while (current && current !== stage) {
    const id = current?.attrs?.id;
    if (typeof id === "string" && id.startsWith("node-")) return true;
    current = current?.getParent?.();
  }
  return false;
}

function handleStageMouseDown(e: any) {
  // 背景编辑模式：让背景图自己拖，不抢事件
  if (bgEditMode.value && backgroundImage.value) {
    isPanning = false;
    return;
  }
  if (isNodeDragTarget(e.target)) {
    isPanning = false;
    return;
  }
  // 其余情况「按在哪都能拖图」：以前只在空白处（target === stage）才平移，
  // 而这张地图几乎被省份面图层盖满，鼠标一落在面上就拖不动了。
  panMoved = false;
  startGpuPanAt(e.evt.clientX, e.evt.clientY);
}

function handleStageTouchStart(e: any) {
  const touches: TouchList | undefined = e.evt?.touches;
  if (!touches || !touches.length) return;
  if (touches.length >= 2) {
    beginPinch(touches);
    return;
  }
  if (bgEditMode.value && backgroundImage.value) return;
  if (isNodeDragTarget(e.target)) return;
  const touch = touches[0];
  if (!touch) return;
  panMoved = false;
  startGpuPanAt(touch.clientX, touch.clientY);
}

/** 双指缩放：以两指中点为锚点，松手后提交给 stage */
function beginPinch(touches: TouchList) {
  finishGpuPan();
  const stage = stageRef.value?.getStage();
  const wrapper = canvasWrapper.value;
  const first = touches[0];
  const second = touches[1];
  if (!stage || !wrapper || !first || !second) return;
  const container = stage.container() as HTMLElement;
  const rect = wrapper.getBoundingClientRect();
  const midX = (first.clientX + second.clientX) / 2 - rect.left;
  const midY = (first.clientY + second.clientY) / 2 - rect.top;
  pinchStartDistance =
    Math.hypot(first.clientX - second.clientX, first.clientY - second.clientY) || 1;
  zoomPreviewActive = true;
  zoomBaseScale = stage.scaleX() || 1;
  zoomBaseX = stage.x();
  zoomBaseY = stage.y();
  zoomCurrentScale = zoomBaseScale;
  zoomCurrentX = zoomBaseX;
  zoomCurrentY = zoomBaseY;
  pinchContentX = (midX - zoomBaseX) / zoomBaseScale;
  pinchContentY = (midY - zoomBaseY) / zoomBaseScale;
  container.style.transformOrigin = "0 0";
  container.style.willChange = "transform";
  pinchActive = true;
  window.addEventListener("touchmove", handleWindowTouchMove, { passive: false });
  window.addEventListener("touchend", handleWindowTouchEnd);
  window.addEventListener("touchcancel", handleWindowTouchEnd);
}

function handleStageMouseMove() {
  // 平移由 window 级 pointer 位移 + GPU transform 处理，这里不重绘
}

function handleStageMouseUp() {
  finishGpuPan();
}

function handleStageClick(e: any) {
  if (panMoved || e.target !== e.target.getStage() || stageOnMove) return;
  const pos = getCanvasPos(e);
  let nearest: MapNode | null = null;
  let nearestDistance = 18;
  for (const node of visibleNodes.value) {
    if (navMode.value && !isNavSelectable(node)) continue;
    const point = nodePos(node);
    const distance = Math.hypot(point.x - pos.x, point.y - pos.y);
    if (distance <= nearestDistance) {
      nearest = node;
      nearestDistance = distance;
    }
  }
  if (nearest) onNodeClick(nearest);
}

function handleStageDblClick(e: any) {
  if (!canEdit.value) return;
  if (e.target !== e.target.getStage()) return;
  const pos = getCanvasPos(e);
  pendingCreatePos.value = { x: pos.x, y: pos.y };
  openCreateDialog();
}

function handleStageWheel(e: any) {
  e.evt.preventDefault();
  const stage = stageRef.value?.getStage();
  const wrapper = canvasWrapper.value;
  if (!stage || !wrapper) return;
  if (isPanning) finishGpuPan();

  const container = stage.container() as HTMLElement;
  if (!zoomPreviewActive) {
    zoomPreviewActive = true;
    zoomBaseScale = stage.scaleX();
    zoomBaseX = stage.x();
    zoomBaseY = stage.y();
    zoomCurrentScale = zoomBaseScale;
    zoomCurrentX = zoomBaseX;
    zoomCurrentY = zoomBaseY;
    container.style.transformOrigin = "0 0";
    container.style.willChange = "transform";
  }

  const rect = wrapper.getBoundingClientRect();
  const pointerX = e.evt.clientX - rect.left;
  const pointerY = e.evt.clientY - rect.top;
  const contentX = (pointerX - zoomCurrentX) / zoomCurrentScale;
  const contentY = (pointerY - zoomCurrentY) / zoomCurrentScale;

  const scaleBy = 1.08;
  const factor = e.evt.deltaY > 0 ? 1 / scaleBy : scaleBy;
  const nextScale = Math.max(0.2, Math.min(5, zoomCurrentScale * factor));
  zoomCurrentScale = nextScale;
  zoomCurrentX = pointerX - contentX * nextScale;
  zoomCurrentY = pointerY - contentY * nextScale;

  // CSS 变换叠加在“已渲染画面”上，拖动/滚轮期间不重绘 Canvas
  const k = zoomCurrentScale / zoomBaseScale;
  const tx = zoomCurrentX - k * zoomBaseX;
  const ty = zoomCurrentY - k * zoomBaseY;
  container.style.transform = `translate3d(${tx}px, ${ty}px, 0) scale(${k})`;

  if (zoomTimer) clearTimeout(zoomTimer);
  zoomTimer = setTimeout(commitGpuZoom, 180);
}

function commitGpuZoom() {
  if (!zoomPreviewActive) return;
  const stage = stageRef.value?.getStage();
  const container = stage?.container() as HTMLElement | undefined;
  if (stage && container) {
    stage.scale({ x: zoomCurrentScale, y: zoomCurrentScale });
    stage.position({ x: zoomCurrentX, y: zoomCurrentY });
    container.style.transform = "";
    container.style.transformOrigin = "";
    container.style.willChange = "";
    stage.batchDraw();
  }
  zoomPreviewActive = false;
  if (zoomTimer) {
    clearTimeout(zoomTimer);
    zoomTimer = null;
  }
}

function handleStageContextMenu(e: any) {
  e.evt.preventDefault();
  if (!canEdit.value) return;
  const pos = { x: e.evt.clientX, y: e.evt.clientY };
  if (e.target === e.target.getStage()) {
    const canvasPos = getCanvasPos(e);
    contextMenu.visible = true;
    contextMenu.x = pos.x;
    contextMenu.y = pos.y;
    contextMenu.type = "stage";
    contextMenu.data = canvasPos;
  }
}

function selectNode(node: MapNode) {
  if (stageOnMove) return;

  if (connectMode.value) {
    if (!connectFrom.value) {
      connectFrom.value = node;
      ElMessage.info(`已选择起点：${node.name}，请点击终点`);
      return;
    }
    if (connectFrom.value.id === node.id) {
      ElMessage.warning("不能连接自身");
      return;
    }
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
  const pos = nodePos(node);
  const s = stageSize.value;
  stage.x(s.width / 2 - pos.x * stageScale.value);
  stage.y(s.height / 2 - pos.y * stageScale.value);
  stage.batchDraw();
}

function handleNodeDragStart(node: MapNode) {
  selectNode(node);
}

// 拖拽实时写回画布坐标：防止响应式重渲染拉回节点，并让相连的边跟随
function handleNodeDragMove(node: MapNode) {
  const grp = stageRef.value?.getStage()?.findOne(`#node-${node.id}`);
  if (!grp) return;
  dragPos.value = { ...dragPos.value, [node.id]: { x: grp.x(), y: grp.y() } };
}

async function handleNodeDragEnd(node: MapNode) {
  const grp = stageRef.value?.getStage()?.findOne(`#node-${node.id}`);
  if (!grp) return;
  const px = grp.x();
  const py = grp.y();
  const stored = toStorage(px, py);
  try {
    await mapNodeApi.update(props.cid, node.id, {
      x: isGeo.value ? stored.x : Math.round(stored.x),
      y: isGeo.value ? stored.y : Math.round(stored.y),
    });
    node.x = stored.x;
    node.y = stored.y;
  } catch (err) {
    const pos = nodePos(node);
    grp.x(pos.x);
    grp.y(pos.y);
    ElMessage.error(errorMessage(err, "操作失败"));
  } finally {
    const next = { ...dragPos.value };
    delete next[node.id];
    dragPos.value = next;
  }
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

function selectEdge(edge: MapEdge) {
  if (stageOnMove) return;
  selectedNode.value = null;
  selectedEdge.value = edge;
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

function openCreateDialog() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛列表」中选择一个比赛");
    return;
  }
  createDialogVisible.value = true;
}

function openCreateAtContext() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛列表」中选择一个比赛");
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
      const stored = toStorage(pendingCreatePos.value.x, pendingCreatePos.value.y);
      await mapNodeApi.create(props.cid, {
        name: createForm.name,
        region: createForm.region || "",
        nodeTypeId: createForm.nodeTypeId,
        x: isGeo.value ? stored.x : Math.round(stored.x),
        y: isGeo.value ? stored.y : Math.round(stored.y),
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

function fitCanvas() {
  const stage = stageRef.value?.getStage();
  if (!stage) return;
  stage.x(0);
  stage.y(0);
  stage.scale({ x: 1, y: 1 });
  stageScale.value = 1;

  if (nodes.value.length > 0) {
    let minX = Infinity,
      minY = Infinity,
      maxX = -Infinity,
      maxY = -Infinity;
    nodes.value.forEach((n) => {
      const p = nodePos(n);
      if (p.x < minX) minX = p.x;
      if (p.y < minY) minY = p.y;
      if (p.x > maxX) maxX = p.x;
      if (p.y > maxY) maxY = p.y;
    });
    const w = maxX - minX + NODE_RADIUS * 6;
    const h = maxY - minY + NODE_RADIUS * 6;
    if (w > 0 && h > 0) {
      const scaleX = stageSize.value.width / w;
      const scaleY = stageSize.value.height / h;
      const s = Math.min(scaleX, scaleY, 1.5);
      stageScale.value = s;
      stage.scale({ x: s, y: s });
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

function openNodeTypeCreate() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛列表」中选择一个比赛");
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
    `确定删除节点类型「${row.name}」？该类型下的所有地图节点及其关联边将一并删除，且不可恢复。`,
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

function openPathTypeCreate() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛列表」中选择一个比赛");
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
    `确定删除路径类型「${row.name}」？使用该类型的所有地图边及载具通行配置将一并删除，且不可恢复。`,
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

function closeContextMenu() {
  contextMenu.visible = false;
}

// 背景 URL + 变换持久化在服务端（按 cid 隔离），支持显示/拖拽/缩放
const backgroundMeta = ref<BackgroundMeta | null>(null);
const backgroundImage = ref<HTMLImageElement | null>(null);
// 背景覆盖框（节点包围盒 + 留白），在加载时冻结，避免节点拖拽时背景抖动。
const bgBBox = ref<{ x: number; y: number; w: number; h: number } | null>(null);
const bgUrlDialogVisible = ref(false);
const bgUrlInput = ref("");
const uploadingBg = ref(false);
const bgFile = ref<File | null>(null);
const bgFileName = ref("");
const bgFileInput = ref<HTMLInputElement | null>(null);
const bgEditMode = ref(false);
// transform 为 null 时按节点包围盒自动适配
const bgTransform = ref<{ x: number; y: number; scale: number } | null>(null);
const BG_PADDING = 160; // 留白，避免边缘节点压图边

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

// auto 显示矩形：等比 cover 铺满包围盒并居中；编辑态/重置复用它，切换时不跳尺寸
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

// 仅 auto 模式重锚：手动变换保持用户设置，auto 始终跟随节点包围盒
function recomputeBBoxIfAuto() {
  if (bgTransform.value) return;
  if (!nodes.value.length) {
    bgBBox.value = null;
    return;
  }
  bgBBox.value = computeBBox();
}

// 节点数组整体替换时重锚；deep:false 下拖拽不触发，故不抖动
watch(
  nodes,
  () => {
    recomputeBBoxIfAuto();
  },
  { deep: false },
);

function applyBackgroundMeta(meta: BackgroundMeta | null) {
  backgroundMeta.value = meta || null;
  if (!meta || !meta.url) {
    backgroundImage.value = null;
    bgBBox.value = null;
    bgTransform.value = null;
    bgEditMode.value = false;
    return;
  }
  bgTransform.value = meta.transform ? { ...meta.transform } : null;
  const img = new Image();
  // 不设 crossOrigin：跨源仅影响 toDataURL 导出（非核心路径）
  img.onload = () => {
    backgroundImage.value = img;
    recomputeBBoxIfAuto();
  };
  img.onerror = () => {
    backgroundImage.value = null;
    bgBBox.value = null;
    ElMessage.error("背景图加载失败");
  };
  img.src = meta.url;
}

async function loadBackground() {
  if (!props.cid) {
    applyBackgroundMeta(null);
    return;
  }
  try {
    const meta = await getMapBackground(props.cid);
    applyBackgroundMeta(meta && meta.url ? meta : null);
  } catch (err) {
    applyBackgroundMeta(null);
    ElMessage.error(errorMessage(err, "背景图加载失败"));
  }
}

function openBgUrlDialog() {
  if (!props.cid) {
    ElMessage.warning("请先在「比赛列表」中选择一个比赛");
    return;
  }
  if (!canEdit.value) {
    ElMessage.warning("无权操作地图背景");
    return;
  }
  bgFile.value = null;
  bgFileName.value = "";
  bgUrlInput.value = backgroundMeta.value?.url ?? "";
  bgUrlDialogVisible.value = true;
}

function resetBgDialog() {
  bgFile.value = null;
  bgFileName.value = "";
  if (bgFileInput.value) bgFileInput.value.value = "";
}

function pickBgFile() {
  bgFileInput.value?.click();
}

function onBgFileSelected(e: Event) {
  const input = e.target as HTMLInputElement;
  const file = input.files?.[0] ?? null;
  bgFile.value = file;
  bgFileName.value = file ? file.name : "";
  if (file) bgUrlInput.value = "";
}

async function confirmBackground() {
  if (!props.cid) return;
  const file = bgFile.value;
  const url = bgUrlInput.value.trim();
  if (!file && !url) {
    ElMessage.warning("请选择图片文件或粘贴图片 URL");
    return;
  }
  if (!file && !/^https?:\/\//i.test(url) && !url.startsWith("data:image/")) {
    ElMessage.warning("图片 URL 需以 http(s):// 或 data:image/ 开头");
    return;
  }
  uploadingBg.value = true;
  try {
    const meta = await saveMapBackground(props.cid, file ? { file } : { url, transform: null });
    applyBackgroundMeta(meta && meta.url ? meta : null);
    ElMessage.success("地图背景已更新");
    bgUrlDialogVisible.value = false;
  } catch (err) {
    ElMessage.error(errorMessage(err, "操作失败"));
  } finally {
    uploadingBg.value = false;
  }
}

async function clearBackground() {
  if (!props.cid) return;
  try {
    await ElMessageBox.confirm("确定清除地图背景图？此操作不可恢复。", "清除地图背景", {
      type: "warning",
      confirmButtonText: "清除",
      cancelButtonText: "取消",
    });
  } catch {
    return;
  }
  try {
    await deleteMapBackground(props.cid);
    applyBackgroundMeta(null);
    ElMessage.success("地图背景已清除");
  } catch (err) {
    ElMessage.error(errorMessage(err, "操作失败"));
  }
}

// 非编辑态 listening=false 不拦截事件；编辑态可拖拽缩放
const backgroundConfig = computed(() => {
  if (!backgroundImage.value) return undefined;
  const img = backgroundImage.value;
  // GEO 模式：底图按导入的经纬度范围铺满画布（QGIS 导出图与数据同范围）
  const g = geoView.value;
  if (g) {
    return {
      image: img,
      x: g.x,
      y: g.y,
      width: g.w,
      height: g.h,
      draggable: false,
      listening: false,
      opacity: 0.85,
    };
  }
  const t = bgTransform.value;
  if (t) {
    // 手动模式按图片原始尺寸 × scale 显示，与节点无关，重进界面可完全复现
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

const bgScale = computed({
  get: () => bgTransform.value?.scale ?? 1,
  set: (v: number) => {
    if (!bgTransform.value) {
      const r = getAutoRect();
      bgTransform.value = { x: r.x, y: r.y, scale: v };
    } else {
      bgTransform.value = { ...bgTransform.value, scale: v };
    }
  },
});

function toggleBgEditMode() {
  if (!backgroundImage.value) return;
  const entering = !bgEditMode.value;
  if (entering && !bgTransform.value) {
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

function handleBgDragEnd(e: any) {
  const node = e?.target;
  if (!node) return;
  const x = node.x();
  const y = node.y();
  if (!bgTransform.value) {
    const r = getAutoRect();
    const iw = backgroundImage.value?.naturalWidth || 800;
    const cover = r.w / iw;
    bgTransform.value = { x, y, scale: cover };
  } else {
    bgTransform.value = { ...bgTransform.value, x, y };
  }
  persistTransform();
}

function resetBgTransform() {
  const r = getAutoRect();
  const iw = backgroundImage.value?.naturalWidth || 800;
  const cover = r.w / iw;
  bgTransform.value = { x: r.x, y: r.y, scale: cover };
  persistTransform();
}

async function persistTransform() {
  const t = bgTransform.value;
  const meta = backgroundMeta.value;
  if (!t || !meta || !props.cid) return;
  if (!canEdit.value) return;
  try {
    const saved = await updateMapBackgroundTransform(props.cid, t);
    backgroundMeta.value = saved && saved.url ? saved : meta;
  } catch (err) {
    ElMessage.error(errorMessage(err, "背景变换保存失败"));
  }
}

let resizeObserver: ResizeObserver | null = null;

function updateStageSize() {
  if (canvasWrapper.value) {
    stageSize.value = {
      width: canvasWrapper.value.clientWidth - 2,
      height: canvasWrapper.value.clientHeight - 2,
    };
  }
}

// 资源变更实时刷新：basedata / files 变更时同步重拉地图数据与背景（保留选中/视图状态）
useResourceRefresh(["basedata", "files"], () => {
  void loadData();
  void loadBackground();
});

onMounted(async () => {
  await loadData();
  await loadBackground();

  updateStageSize();
  if (isPhone.value) legendCollapsed.value = true;

  resizeObserver = new ResizeObserver(() => {
    updateStageSize();
  });
  if (canvasWrapper.value) {
    resizeObserver.observe(canvasWrapper.value);
  }

  document.addEventListener("click", closeContextMenu);

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
    await loadBackground();
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
  /* 高度按数据管理外壳扣除，给画布留足空间 */
  height: calc(100vh - 160px);
  height: calc(100dvh - 160px);
  min-height: 640px;
  background: var(--surface-sunken);
}

.mm-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 0 12px;
  flex-shrink: 0;
}
.mm-title {
  margin: 0;
}
.mm-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.mm-body {
  flex: 1;
  display: flex;
  gap: 0;
  min-height: 480px;
  overflow: hidden;
  background: var(--color-surface);
  border-radius: 8px;
  border: 1px solid var(--color-border-strong);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}

.mm-left-panel {
  width: 210px;
  min-width: 190px;
  background: var(--surface-inverse);
  color: var(--surface-inverse-fg);
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
  color: var(--surface-inverse-fg-muted);
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
  color: var(--surface-inverse-fg);
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
  /* 只过渡背景/颜色，不做位移以免长列表抖动 */
  transition:
    background var(--dur-fast) var(--ease-standard),
    color var(--dur-fast) var(--ease-standard),
    box-shadow var(--dur-fast) var(--ease-standard);
  font-size: 13px;
  color: var(--surface-inverse-fg-muted);
  box-shadow: inset 2px 0 0 transparent;
}
.node-item:hover {
  background: rgba(255, 255, 255, 0.06);
}
.node-item:focus-visible {
  outline: 2px solid rgba(64, 158, 255, 0.75);
  outline-offset: -2px;
}
.node-item.active {
  background: rgba(64, 158, 255, 0.15);
  color: var(--surface-inverse-fg);
  box-shadow: inset 2px 0 0 var(--color-primary);
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

.mm-canvas-wrapper {
  flex: 1;
  overflow: hidden;
  background: #f0f2f5;
  position: relative;
  /* 触屏：滚动手势不要抢，交给地图自己平移/缩放 */
  touch-action: none;
}

.picked-region {
  position: absolute;
  z-index: 5;
  top: 12px;
  left: 12px;
  padding: 6px 10px;
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.92);
  color: #374151;
  font-size: 12px;
  box-shadow: 0 2px 8px rgba(31, 41, 55, 0.08);
}

.map-import-missing {
  margin-top: 8px;
}

.nav-panel {
  position: absolute;
  z-index: 15;
  top: 12px;
  left: 12px;
  width: 290px;
  max-height: calc(100% - 24px);
  overflow-y: auto;
  padding: 12px 14px;
  border: 1px solid var(--color-border-strong);
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.97);
  box-shadow: 0 6px 20px rgba(31, 41, 55, 0.12);
}

.nav-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.nav-title {
  color: #1f2937;
  font-size: 14px;
  font-weight: 600;
}

.nav-hint {
  margin: 4px 0 10px;
  color: #9ca3af;
  font-size: 12px;
}

.nav-endpoint {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  margin-bottom: 6px;
  font-size: 13px;
}

.nav-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 auto;
  border-radius: 50%;
}
.nav-dot-start { background: #16a34a; }
.nav-dot-end { background: #ef4444; }

.nav-label {
  flex: 0 0 auto;
  color: #6b7280;
}

.nav-name {
  overflow: hidden;
  color: #1f2937;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.nav-actions {
  display: flex;
  gap: 8px;
  margin: 8px 0;
}

.nav-form {
  margin-top: 4px;
}

.nav-types {
  display: flex;
  flex-wrap: wrap;
  gap: 0 8px;
}

.nav-result {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid #eef0f4;
}

.nav-result-line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
  color: #f59e0b;
  font-size: 16px;
}

.nav-result-line span {
  color: #6b7280;
  font-size: 12px;
}

.nav-steps {
  max-height: 150px;
  margin-top: 8px;
  overflow-y: auto;
  color: #374151;
  font-size: 12px;
  line-height: 1.7;
}

.nav-segments {
  margin-top: 6px;
  color: #9ca3af;
  font-size: 11px;
  line-height: 1.6;
}

.nav-summary {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed #e5e7eb;
}

.nav-summary-title {
  margin-bottom: 4px;
  color: #6b7280;
  font-size: 11px;
}

.nav-summary-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 12px;
  color: #4b5563;
  font-size: 12px;
}

.nav-summary-row b {
  color: #1f2937;
  font-weight: 600;
}

.bg-edit-panel {
  position: absolute;
  left: 16px;
  bottom: 16px;
  z-index: 20;
  width: 320px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid var(--color-border-strong);
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
  backdrop-filter: blur(2px);
}
.bg-edit-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
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
  color: var(--color-text-secondary);
  flex-shrink: 0;
}
.bg-edit-slider {
  flex: 1;
}
.bg-edit-val {
  font-size: 13px;
  color: var(--color-primary);
  width: 44px;
  text-align: right;
  flex-shrink: 0;
}
.bg-edit-hint {
  font-size: 12px;
  color: var(--color-text-tertiary);
}

.bg-file-name {
  margin-left: 10px;
  font-size: 12px;
  color: var(--color-text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}

.mm-mode-tag {
  margin-left: 2px;
}

/* QGIS 地图导入 */
.map-import-form {
  margin-top: 14px;
}

.map-import-report {
  margin-top: 4px;
  padding: 12px 14px;
  background: var(--surface-sunken);
  border-radius: var(--radius-sm);
}

.map-import-report__title {
  font-weight: 600;
  font-size: 13px;
  color: var(--color-text-primary);
  margin-bottom: 8px;
}

.map-import-report__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px 12px;
  font-size: 13px;
  color: var(--color-text-secondary);
}

.map-import-report__grid b {
  color: var(--color-text-primary);
}

.map-import-report__bounds {
  margin-top: 8px;
  font-size: 12px;
  color: var(--color-text-tertiary);
}

.mm-legend-panel {
  position: absolute;
  right: 16px;
  top: 16px;
  z-index: 20;
  width: 220px;
  max-height: calc(100% - 32px);
  display: flex;
  flex-direction: column;
  background: rgba(255, 255, 255, 0.96);
  border: 1px solid var(--color-border-strong);
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
  border-bottom: 1px solid var(--color-border-strong);
}
.legend-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
}
.legend-caret {
  font-size: 12px;
  color: var(--color-text-tertiary);
}
.legend-body {
  padding: 10px 12px;
  flex: 1;
  min-height: 0;
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
  color: var(--color-text-secondary);
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
.legend-dot-connected {
  background: var(--color-primary);
}

.legend-dot-isolated {
  box-sizing: border-box;
  background: var(--color-surface);
  border: 2px dashed #d946ef;
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
  color: var(--color-text-primary);
}
.legend-empty {
  font-size: 12px;
  color: var(--color-text-tertiary);
}

.mm-right-panel {
  width: 250px;
  min-width: 230px;
  background: var(--color-surface);
  border-left: 1px solid var(--color-border-strong);
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
  border-bottom: 1px solid var(--color-border-strong);
}
.mm-right-panel .panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--color-text-primary);
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
  color: var(--color-text-tertiary);
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
  color: var(--color-text-secondary);
  font-size: 13px;
}

.mm-bottom {
  flex-shrink: 0;
  margin-top: 12px;
  background: var(--color-surface);
  border-radius: 8px;
  border: 1px solid var(--color-border-strong);
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.04);
}
.mm-bottom :deep(.el-tabs--border-card) {
  border: none;
  box-shadow: none;
}
.mm-bottom :deep(.el-tabs--border-card > .el-tabs__header) {
  background: var(--surface-sunken);
  border-bottom: 1px solid var(--color-border-strong);
}
.tab-toolbar {
  padding: 10px 0;
  display: flex;
  gap: 8px;
}

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

.context-menu {
  position: fixed;
  z-index: 3000;
  background: var(--color-surface);
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
  padding: 4px 0;
  min-width: 140px;
  border: 1px solid var(--color-border-strong);
}
.menu-item {
  padding: 8px 16px;
  font-size: 13px;
  cursor: pointer;
  color: var(--color-text-primary);
  transition: background 0.12s;
}
.menu-item:hover {
  background: #f0f2f5;
}

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

/* 手机端抽屉，避免遮挡地图 */
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
  .mm-drawer-mask {
    position: absolute;
    inset: 0;
    z-index: 39;
    background: rgba(0, 0, 0, 0.25);
  }
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
  /* 窄屏避免超出视口 */
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
